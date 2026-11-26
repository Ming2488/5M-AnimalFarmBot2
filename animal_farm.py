import ctypes
import sys
import threading
import time
from collections import namedtuple
from ctypes import wintypes
from pathlib import Path

# ต้องตั้งก่อนอย่างอื่น: ให้พิกัดเป็นพิกเซลจริงทุกจอ (กันคลิกเพี้ยนเวลามีหลายจอ/ซูม Windows)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import cv2
import keyboard
import numpy as np
from PIL import Image, ImageGrab

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

if user32 is not None:
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

# ==============================
# SETTINGS
# ==============================

BASE_DIR = Path(__file__).resolve().parent

BUY = str(BASE_DIR / "animal_buy_button.png")
FEED = str(BASE_DIR / "animal_feed_button.png")
COLLECT = str(BASE_DIR / "animal_collect_button.png")

# --- รูปสำหรับระบบเก็บเนื้อเข้ารถ (ตัดจากหน้าจอเกม ขนาดพิกเซลจริง) ---
GARAGE_HEADER = str(BASE_DIR / "animal_garage_header.png")   # ป้าย GARAGE VEHICLE
CAR_CARD = str(BASE_DIR / "animal_car_card.png")             # ชื่อรถ+ป้ายทะเบียนบนการ์ดรถ
OPEN_TRUNK = str(BASE_DIR / "animal_open_trunk_button.png")  # ปุ่ม Open Trunk
BEEF = str(BASE_DIR / "animal_beef_item.png")                # ไอคอนเนื้อ A1 Beef (ไม่เอาตัวเลข)
MAX_BTN = str(BASE_DIR / "animal_max_button.png")            # ปุ่ม MAX  <-- ต้องตัดภาพมาเพิ่ม
CONFIRM = str(BASE_DIR / "animal_confirm_button.png")        # ปุ่ม Confirm
TRUNK_FULL = str(BASE_DIR / "animal_trunk_full.png")         # (ไม่บังคับ) ข้อความ/ภาพตอนรถเต็ม

TRUNK_IMAGES = [GARAGE_HEADER, CAR_CARD, OPEN_TRUNK, BEEF, MAX_BTN, CONFIRM]

BUY_CONFIDENCE = 0.85
CONFIDENCE = 0.88

CHECK_INTERVAL = 0.5

# ความเร็ว (หน่วยวินาที) ยิ่งน้อยยิ่งเร็ว ถ้าเกมเริ่มคลิกพลาดให้เพิ่มกลับ
CLICK_SETTLE = 0.02          # รอหลังเลื่อนเมาส์ไปที่ปุ่ม ก่อนกด
CLICK_HOLD = 0.02            # ระยะกดค้าง
AFTER_CLICK = 0.02           # รอหลังปล่อยเมาส์
BUY_WAIT = 0.2               # รอหลังกดซื้อแต่ละครั้ง ก่อนหาปุ่มซื้ออีกรอบ
CONFIRM_INTERVAL = 0.02      # เช็กว่าปุ่มหายหลังคลิกทุกกี่วินาที
FULL_SCAN_INTERVAL = 0.2     # สแกนทั้งหน้าต่างเพื่อหาปุ่มตำแหน่งใหม่ทุกกี่วินาที (ช้า) ที่เหลือเช็กเฉพาะจุดที่เคยเจอ (เร็วมาก)
CLICK_COOLDOWN = 0.7         # หลังคลิกปุ่มหนึ่ง ไม่คลิกจุดเดิมซ้ำภายในกี่วินาที (ไม่ต้องรอให้ปุ่มหาย)

AUTO_BUY = True              # True = บอทกดซื้อให้ด้วย / False = ไม่ซื้อ (คุณซื้อเอง)
MAX_BUY_CLICKS = 10          # กันบอทกดซื้อวนไม่จบ (ถ้าจับปุ่มซื้อผิดที่)
IDLE_LIMIT = 0               # รอปุ่มให้อาหาร/เก็บสูงสุดกี่วินาทีแล้วจบรอบ (0 = รอไปเรื่อยๆ จนกว่าจะกดหยุด)

OPEN_MENU_KEY = "h"          # ปุ่มเปิดเมนูฟาร์มในเกม

# ---- ระบบเก็บเนื้อเข้ารถ ----
AUTO_TRUNK = True            # True = เก็บครบแล้วไปฝากเนื้อที่ตู้แดง/รถให้อัตโนมัติ
COLLECTS_PER_TRIP = 10       # กดเก็บผลผลิตครบกี่ครั้งถึงไปฝากเนื้อ 1 รอบ
MAX_TRIPS = 0                # ฝากสูงสุดกี่รอบ (0 = ไม่จำกัด จนกว่ารถเต็ม/กดหยุด)
INTERACT_KEY = "e"           # ปุ่มเปิดโรงรถที่ตู้แดง
CLOSE_KEY = "esc"            # ปุ่มปิดหน้าต่าง (เมนูฟาร์ม/โรงรถ/ท้ายรถ)
CAR_CLICK_OFFSET = (104, 98) # จุดคลิกขวาบนการ์ดรถ วัดจากมุมซ้ายบนของรูป CAR_CARD
TRUNK_STEP_TIMEOUT = 5       # รอแต่ละขั้น (วินาที) ถ้าไม่เจอปุ่มถือว่าพลาด
TRUNK_UI_DELAY = 0.25        # หน่วงหลังคลิกในหน้าต่างท้ายรถ ให้ UI ตอบสนองทัน

# ---- การลากเนื้อไปฝั่งท้ายรถ (ช่องฝั่งขวาของหน้าต่างกระเป๋า) ----
# จุดที่ปล่อยเนื้อ เป็นสัดส่วนของหน้าต่างเกม (x, y) 0.0-1.0
# ค่าเริ่มต้นวัดจากภาพหน้าจอ 1920x1080: ช่องท้ายรถอยู่ราว x 55%-87%, y 21%-82%
TRUNK_DROP_FRAC = (0.71, 0.50)

# ---- ขอบเขตค้นหาเนื้อ "เฉพาะฝั่งกระเป๋าผู้เล่น (ซ้าย)" ----
# ไอคอนเนื้อฝั่งกระเป๋ากับฝั่งท้ายรถหน้าตาเหมือนกัน และรูป animal_beef_item.png
# ถูกตัดมาจากฝั่งท้ายรถ (คะแนน 0.99) จึงเคยจับผิดไปหยิบฝั่งขวา
# ช่องกระเป๋าอยู่ราว x 22%-52% ของหน้าต่าง, ช่องท้ายรถเริ่มราว x 55% (ภาพ 1920x1080)
# ค่าเป็นสัดส่วนของหน้าต่างเกม: (x เริ่ม, y เริ่ม, x จบ, y จบ)
INVENTORY_REGION_FRAC = (0.20, 0.18, 0.535, 0.84)
BEEF_INV_CONFIDENCE = 0.80   # ต่ำกว่า CONFIDENCE เพราะรูปตัดมาจากฝั่งขวา (ฝั่งซ้ายได้ราว 0.92)
DRAG_STEPS = 14              # แบ่งการลากเป็นกี่ช่วง (เกมส่วนใหญ่ไม่รับการวาร์ปเมาส์ครั้งเดียว)
DRAG_STEP_DELAY = 0.02       # หน่วงระหว่างแต่ละช่วงของการลาก
DRAG_GRAB_DELAY = 0.15       # กดค้างบนไอเทมก่อนเริ่มขยับ ให้เกมจับว่าเริ่มลาก
DRAG_DROP_DELAY = 0.2        # ถึงปลายทางแล้วรอก่อนปล่อย ให้ช่องปลายทางไฮไลต์ทัน
DRAG_RETRIES = 2             # ลากไม่สำเร็จ (ไม่มี MAX/Confirm ขึ้น) ลองซ้ำกี่ครั้ง
MAX_CONFIDENCE = 0.78        # คะแนนขั้นต่ำของปุ่ม MAX (ค้นหาหลายขนาด เพราะรูปที่ตัดมาใหญ่กว่าปุ่มจริงในเกม)
AFTER_DRAG_WAIT = 2.5        # หลังปล่อย รอหน้าต่าง MAX/Confirm ขึ้นสูงสุดกี่วินาที
START_DELAY = 5             # วินาทีที่ให้คลิกกลับเข้าเกมหลังกด START

# ปุ่มลัดของบอท (แก้ได้ เช่น "ctrl+alt+s")
KEY_START = "ctrl+a"
KEY_STOP = "ctrl+s"
KEY_TEST = "ctrl+d"      # ทดสอบว่าหาปุ่มเจอไหม (ไม่คลิกอะไร)
KEY_TRUNK_TEST = "ctrl+f"  # ทดสอบเฉพาะรอบฝากเนื้อ (ข้ามฟาร์ม คลิกจริง 1 รอบ)

# บอทจะค้นหาปุ่มเฉพาะ "หน้าต่างที่คุณคลิกค้างไว้ตอนครบ START_DELAY"
# ถ้าไม่ใช่หน้าต่างเกม (ชื่อไม่มีคำเหล่านี้) บอทจะไม่คลิกอะไรเลย
CHECK_GAME_TITLE = True
GAME_TITLE_KEYWORDS = ["fivem", "grand theft auto", "gta"]

stop_event = threading.Event()
running = False
GAME_RECT = None             # (left, top, width, height) ของหน้าต่างเกม

Box = namedtuple("Box", "left top width height")


# ==============================
# BASIC FUNCTIONS
# ==============================

def log(msg):
    print("[BOT]", msg, flush=True)


def wait(seconds):
    return not stop_event.wait(seconds)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def foreground_window():
    """คืนค่า (ชื่อหน้าต่าง, (left, top, width, height)) ของหน้าต่างที่ active อยู่"""
    hwnd = user32.GetForegroundWindow()
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value, (rect.left, rect.top,
                       rect.right - rect.left, rect.bottom - rect.top)


# ---- ส่งปุ่มแบบ scan code (เกมส่วนใหญ่รับแบบนี้) ----

SCAN_CODES = {
    "esc": 0x01, "enter": 0x1C, "space": 0x39,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14,
    "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22,
    "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
    "n": 0x31, "m": 0x32,
}

PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", InputUnion)]


KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002


def _send_scan(scan, up=False):
    extra = ctypes.c_ulong(0)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    ii = InputUnion()
    ii.ki = KeyBdInput(0, scan, flags, 0, ctypes.pointer(extra))
    x = Input(1, ii)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))


def press_key(key, hold=0.08):
    scan = SCAN_CODES.get(key.lower())

    if scan is None or user32 is None:
        keyboard.send(key)
        return

    _send_scan(scan)
    time.sleep(hold)
    _send_scan(scan, up=True)


# ---- เมาส์ (ทำเอง ใช้ได้ทุกจอ ไม่โดนจำกัดแค่จอหลัก) ----

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def click_box(box, button="left"):
    click_point(box.left + box.width // 2, box.top + box.height // 2, button)


def click_point(x, y, button="left"):
    if stop_event.is_set():
        return

    down, up = ((MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
                if button == "right"
                else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))

    # FAILSAFE: ถ้าเมาส์อยู่มุมซ้ายบนสุดของจอหลัก ให้หยุดบอททันที
    cx, cy = cursor_pos()
    if cx <= 2 and cy <= 2:
        stop_event.set()
        log("FAILSAFE: เมาส์อยู่มุมซ้ายบน -> หยุดบอท")
        return

    # ถ้าเมาส์อยู่ที่ปุ่มอยู่แล้ว (เช่น กดซื้อซ้ำที่เดิม) ไม่ต้องขยับ
    if (cx, cy) != (x, y):
        user32.SetCursorPos(x + 2, y)
        time.sleep(0.01)
        user32.SetCursorPos(x, y)
        time.sleep(CLICK_SETTLE)

    user32.mouse_event(down, 0, 0, 0, 0)
    time.sleep(CLICK_HOLD)
    user32.mouse_event(up, 0, 0, 0, 0)
    time.sleep(AFTER_CLICK)


def drag_point(x1, y1, x2, y2):
    """กดซ้ายค้างที่ (x1,y1) ค่อยๆ ขยับเมาส์ไป (x2,y2) เป็นหลายช่วง แล้วปล่อย
    คืน True ถ้าลากจบครบ (ไม่ได้ถูกสั่งหยุดกลางทาง)"""
    if stop_event.is_set():
        return False

    cx, cy = cursor_pos()
    if cx <= 2 and cy <= 2:
        stop_event.set()
        log("FAILSAFE: เมาส์อยู่มุมซ้ายบน -> หยุดบอท")
        return False

    # ไปที่ไอเทมต้นทาง
    user32.SetCursorPos(x1 + 2, y1)
    time.sleep(0.01)
    user32.SetCursorPos(x1, y1)
    time.sleep(CLICK_SETTLE + 0.05)

    done = False
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    try:
        time.sleep(DRAG_GRAB_DELAY)

        # ขยับเป็นช่วงเล็กๆ จนถึงปลายทาง
        for i in range(1, DRAG_STEPS + 1):
            if stop_event.is_set():
                return False

            t = i / DRAG_STEPS
            user32.SetCursorPos(int(x1 + (x2 - x1) * t),
                                int(y1 + (y2 - y1) * t))
            time.sleep(DRAG_STEP_DELAY)

        # ขยับขยิบที่ปลายทาง 1 พิกเซล ให้เกมได้รับ mouse-move จริงๆ ก่อนปล่อย
        user32.SetCursorPos(x2 + 1, y2)
        time.sleep(0.02)
        user32.SetCursorPos(x2, y2)
        time.sleep(DRAG_DROP_DELAY)
        done = True

    finally:
        # ปล่อยปุ่มเมาส์เสมอ (กันปุ่มค้างถ้าโดนสั่งหยุดกลางทาง)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(AFTER_CLICK)

    return done


def drag_box_to_frac(box, frac):
    """ลากจากกลางกล่อง box ไปยังจุดที่เป็นสัดส่วน frac ของหน้าต่างเกม"""
    if GAME_RECT is None:
        return False

    gx, gy, gw, gh = GAME_RECT
    return drag_point(box.left + box.width // 2,
                      box.top + box.height // 2,
                      int(gx + gw * frac[0]),
                      int(gy + gh * frac[1]))


# ---- หารูปบนหน้าจอ (ค้นเฉพาะในหน้าต่างเกม ทุกจอ) ----
# จับคู่แบบ "สี" (ไม่ใช่ขาวดำ) เพราะปุ่มให้อาหาร(ส้ม)กับปุ่มเก็บ(เขียว)
# พอเป็นขาวดำแล้วหน้าตาคล้ายกันมาก จะสับสนกัน

_templates = {}


# ตัดขอบรูปปุ่มทิ้งกี่พิกเซล (ขอบมนของปุ่มซื้อมีสีพื้นหลังติดมา ทำให้คะแนนตก)
CROP_EDGE = {BUY: 6}


def load_template(path):
    if path not in _templates:
        tpl = cv2.cvtColor(
            np.array(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)
        c = CROP_EDGE.get(path, 0)
        if c:
            tpl = tpl[c:-c, c:-c]
        _templates[path] = np.ascontiguousarray(tpl)
    return _templates[path]


def grab_screen(region):
    left, top, w, h = region
    im = ImageGrab.grab(
        bbox=(left, top, left + w, top + h),
        all_screens=True
    )
    return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)


def _match(image, region, screen=None):
    """คืน (ตารางคะแนน, กว้างปุ่ม, สูงปุ่ม, region) หรือ None
    screen = ภาพที่แคปไว้แล้วของ GAME_RECT (ใช้ซ้ำเพื่อประหยัดเวลา)"""
    if region is None:
        region = GAME_RECT

    if region is None:
        return None

    tpl = load_template(image)
    th, tw = tpl.shape[:2]

    if region[2] < tw or region[3] < th:
        return None

    sub = None

    if screen is not None and GAME_RECT is not None:
        gx, gy = GAME_RECT[0], GAME_RECT[1]
        x0, y0 = region[0] - gx, region[1] - gy
        x1, y1 = x0 + region[2], y0 + region[3]

        if (x0 >= 0 and y0 >= 0
                and x1 <= screen.shape[1] and y1 <= screen.shape[0]):
            sub = screen[y0:y1, x0:x1]

    screen = sub if sub is not None else grab_screen(region)

    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
    return res, tw, th, region


def find_one(image, region=None, confidence=CONFIDENCE, screen=None):
    if stop_event.is_set():
        return None

    m = _match(image, region, screen)

    if m is None:
        return None

    res, tw, th, region = m
    _, best, _, loc = cv2.minMaxLoc(res)

    if best < confidence:
        return None

    return Box(region[0] + loc[0], region[1] + loc[1], tw, th)


def find_all(image, confidence=CONFIDENCE, region=None, screen=None):
    if stop_event.is_set():
        return []

    m = _match(image, region, screen)

    if m is None:
        return []

    res, tw, th, region = m
    ys, xs = np.where(res >= confidence)

    candidates = sorted(
        zip(res[ys, xs].tolist(), xs.tolist(), ys.tolist()),
        reverse=True
    )[:500]

    accepted = []

    for score, x, y in candidates:
        if all(abs(x - ax) >= tw // 2 or abs(y - ay) >= th // 2
               for ax, ay in accepted):
            accepted.append((x, y))

    boxes = [Box(region[0] + x, region[1] + y, tw, th) for x, y in accepted]
    return sorted(boxes, key=lambda b: (b.top, b.left))


_last_box = {}


def find_fast(image, confidence=CONFIDENCE, full=True, screen=None):
    """เช็กรอบๆ จุดที่เจอปุ่มครั้งก่อนก่อน (เร็วมาก) ถ้าไม่เจอค่อยสแกนทั้งหน้าต่าง"""
    last = _last_box.get(image)

    if last is not None:
        region = (last.left - 20, last.top - 20,
                  last.width + 40, last.height + 40)
        box = find_one(image, region, confidence)

        if box is not None:
            _last_box[image] = box
            return box

    if not full:
        return None

    box = find_one(image, None, confidence, screen)

    if box is not None:
        _last_box[image] = box

    return box


def wait_until_missing(image, region=None, timeout=15,
                       confidence=CONFIDENCE):
    end = time.time() + timeout

    while time.time() < end:
        if stop_event.is_set():
            return False

        if find_one(image, region, confidence) is None:
            return True

        wait(CONFIRM_INTERVAL)

    return False


# ==============================
# TEST MODE - ไม่คลิกอะไรทั้งนั้น
# ==============================

def test_screen():
    title, rect = foreground_window()
    log(f"TEST: หน้าต่างที่ active = '{title}'  ตำแหน่ง/ขนาด = {rect}")

    ImageGrab.grab(all_screens=True).save(
        str(BASE_DIR / "debug_all_screens.png"))

    if rect[2] > 0 and rect[3] > 0:
        left, top, w, h = rect
        ImageGrab.grab(
            bbox=(left, top, left + w, top + h), all_screens=True
        ).save(str(BASE_DIR / "debug_window.png"))

    checks = [
        ("BUY", BUY, BUY_CONFIDENCE),
        ("FEED", FEED, CONFIDENCE),
        ("COLLECT", COLLECT, CONFIDENCE),
    ]
    checks += [(Path(p).stem.replace("animal_", "").upper(), p, CONFIDENCE)
               for p in TRUNK_IMAGES if Path(p).exists()]

    for name, path, need in checks:
        m = _match(path, rect)

        if m is None:
            log(f"TEST {name}: หน้าต่างเล็กกว่ารูปปุ่ม ค้นไม่ได้")
            continue

        res, tw, th, _ = m
        _, best, _, loc = cv2.minMaxLoc(res)
        verdict = "FOUND" if best >= need else "NOT FOUND"
        log(f"TEST {name}: คะแนนสูงสุด {best:.2f} "
            f"(ต้อง >= {need}) -> {verdict}")

    log("TEST: เปิด debug_window.png / debug_all_screens.png ดูว่าเป็นภาพเกมจริงไหม "
        "(ถ้าดำ = เกมเป็น Fullscreen ให้เปลี่ยนเป็น Borderless)")


def test_thread():
    try:
        test_screen()
    except Exception as e:
        log(f"TEST ERROR: {e!r}")


# ==============================
# 1. BUY UNTIL NO BUTTON
# ==============================

def buy_animals():
    log("BUY START")

    count = 0
    missing = 0

    while not stop_event.is_set():

        button = find_fast(BUY, BUY_CONFIDENCE)

        if stop_event.is_set():
            break

        if button is None:
            missing += 1
            log(f"BUY NOT FOUND {missing}/3")

            if missing >= 3:
                break

            wait(0.2)
            continue

        missing = 0

        log(f"BUY BUTTON FOUND at ({button.left}, {button.top})")
        click_box(button)

        if stop_event.is_set():
            break

        count += 1
        log(f"BUY CLICKED: {count}")

        if count >= MAX_BUY_CLICKS:
            log(f"กดซื้อครบ {MAX_BUY_CLICKS} ครั้งแล้ว -> หยุดซื้อ ไปขั้นให้อาหาร "
                "(ถ้าตำแหน่งที่กดซ้ำๆ ไม่ใช่ปุ่มซื้อ แปลว่าจับผิดที่ "
                "ให้ตั้ง AUTO_BUY = False)")
            break

        # รอเกมประมวลผลก่อนค้นหาปุ่มอีกครั้ง
        if not wait(BUY_WAIT):
            break

    log(f"BUY FINISHED: {count} CLICKS")


# ==============================
# 2. FEED + COLLECT LOOP (รอปุ่มจนกว่าจะไม่มีอะไรขึ้นอีก)
# ==============================

def farm_loop():
    log("FEED/COLLECT LOOP START")
    log("คลิก COLLECT แล้วรอยืนยันว่าปุ่มหาย ก่อนนับ")

    images = {"COLLECT": COLLECT, "FEED": FEED, "BUY": BUY}
    conf = {"COLLECT": CONFIDENCE, "FEED": CONFIDENCE, "BUY": BUY_CONFIDENCE}

    slots = {"COLLECT": [], "FEED": [], "BUY": []}  # ตำแหน่งปุ่มที่เคยเจอ (เช็กเร็วๆ)
    recent = []                                     # (ชื่อ, x, y, เวลาที่คลิก)
    counts = {"COLLECT": 0, "FEED": 0, "BUY": 0}
    buy_capped = False

    def active_order():
        # ลำดับความสำคัญ: เก็บของ > ให้อาหาร > ซื้อ
        names = ["COLLECT", "FEED"]

        if AUTO_BUY and counts["BUY"] < MAX_BUY_CLICKS:
            names.append("BUY")

        return [(n, images[n]) for n in names]

    streak = 0
    last_click = None
    trip = False

    last_full = 0.0
    last_activity = time.time()
    last_report = 0
    last_screen = None

    def near(a, b, tol=12):
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

    def cooling(name, box, now):
        return any(
            n == name and near((x, y), (box.left, box.top))
            and now - t < CLICK_COOLDOWN
            for n, x, y, t in recent
        )

    while not stop_event.is_set():

        now = time.time()
        recent[:] = [r for r in recent if now - r[3] < 5]

        # แคปหน้าจอครั้งเดียวต่อรอบ ใช้ซ้ำกับทุกการค้นหา
        screen = grab_screen(GAME_RECT)
        last_screen = screen

        found = None

        # 1) เช็กจุดที่เคยเจอปุ่ม (เร็วมาก) ลำดับ: เก็บของก่อน แล้วค่อยให้อาหาร
        for name, image in active_order():
            for slot in slots[name]:
                if cooling(name, slot, now):
                    continue

                region = (slot.left - 15, slot.top - 15,
                          slot.width + 30, slot.height + 30)
                box = find_one(image, region, conf[name], screen)

                if box is not None and not cooling(name, box, now):
                    found = (name, box)
                    break

            if found:
                break

        # 2) สแกนทั้งหน้าต่างเป็นช่วงๆ เพื่อหาปุ่มในตำแหน่งใหม่
        if found is None and now - last_full >= FULL_SCAN_INTERVAL:
            for name, image in active_order():
                for box in find_all(image, conf[name], screen=screen):
                    if not any(near((s_.left, s_.top), (box.left, box.top))
                               for s_ in slots[name]):
                        slots[name].append(box)

                    if found is None and not cooling(name, box, now):
                        found = (name, box)

            last_full = time.time()

        if found is None:
            idle = time.time() - last_activity

            if IDLE_LIMIT and idle >= IDLE_LIMIT:
                log("ไม่มีปุ่มขึ้นมานานแล้ว -> จบรอบ")
                break

            if idle - last_report >= 15:
                last_report = int(idle)
                scores = []

                for name, image in (("FEED", FEED), ("COLLECT", COLLECT)):
                    m = _match(image, GAME_RECT, last_screen)

                    if m is not None:
                        best = cv2.minMaxLoc(m[0])[1]
                        scores.append(f"{name} {best:.2f}")

                log(f"WAITING... {int(idle)}s  "
                    f"คะแนนที่เห็นบนจอ: {', '.join(scores)} "
                    f"(ต้อง >= {CONFIDENCE})")

            wait(0.01)
            continue

        name, target = found

        log(f"{name} BUTTON FOUND")

        # ถ้ากดจุดเดิมซ้ำทั้งที่ปุ่มยังอยู่ แปลว่าเกมอาจไม่รับคลิก
        # (ปุ่มซื้อยกเว้น เพราะซื้อได้หลายตัว ปุ่มจึงอยู่ที่เดิมต่อได้)
        if (name != "BUY" and last_click is not None
                and last_click[0] == name
                and near(last_click[1:3], (target.left, target.top))
                and time.time() - last_click[3] < 4):
            streak += 1
        else:
            streak = 0

        if streak >= 3:
            log("กดจุดเดิมซ้ำแล้วปุ่มไม่หาย -> เกมอาจไม่รับคลิกจากบอท "
                "(ลองรันแบบ Administrator / ตั้งเกมเป็น Borderless)")
            stop_event.set()
            break

        click_box(target)

        if stop_event.is_set():
            break

        t = time.time()
        recent.append((name, target.left, target.top, t))
        last_click = (name, target.left, target.top, t)

        # COLLECT: นับเมื่อยืนยันจากภาพว่าปุ่มหายไปจากบริเวณเดิมแล้ว
        if name == "COLLECT":
            confirm_region = (target.left - 25, target.top - 25,
                             target.width + 50, target.height + 50)
            log("COLLECT: รอให้ปุ่มหายเพื่อยืนยัน...")
            confirmed = wait_until_missing(
                COLLECT, region=confirm_region, timeout=4,
                confidence=CONFIDENCE
            )
            if not confirmed:
                if stop_event.is_set():
                    break
                log("COLLECT NOT CONFIRMED: ปุ่มไม่หายภายใน 4 วินาที -> หยุดรอบ ไม่เพิ่มตัวนับ")
                break
            counts[name] += 1
            log(f"COLLECT CONFIRMED: {counts[name]}")
        else:
            counts[name] += 1
            log(f"{name} CLICKED: {counts[name]}")

        if (name == "BUY" and counts["BUY"] >= MAX_BUY_CLICKS
                and not buy_capped):
            buy_capped = True
            log(f"กดซื้อครบ {MAX_BUY_CLICKS} ครั้งแล้ว -> หยุดซื้อ "
                "(เพิ่มได้ที่ MAX_BUY_CLICKS)")

        last_activity = t
        last_report = 0

        if (AUTO_TRUNK and name == "COLLECT"
                and counts["COLLECT"] >= COLLECTS_PER_TRIP):
            log(f"เก็บครบ {COLLECTS_PER_TRIP} ครั้งแล้ว -> ไปฝากเนื้อเข้ารถ")
            trip = True
            break

    log(f"LOOP FINISHED: BUY {counts['BUY']} / FEED {counts['FEED']} "
        f"/ COLLECT {counts['COLLECT']}")

    return "trip" if trip else "end"


# ==============================
# 3. DEPOSIT MEAT INTO CAR TRUNK
# ==============================

def wait_for(image, timeout=TRUNK_STEP_TIMEOUT, confidence=CONFIDENCE):
    """รอจนเจอรูป (สแกนทั้งหน้าต่างเกมสดๆ ทุกรอบ) ไม่เจอในเวลาที่กำหนดคืน None"""
    end = time.time() + timeout

    while time.time() < end and not stop_event.is_set():
        box = find_one(image, None, confidence)

        if box is not None:
            return box

        wait(0.1)

    return None


def inventory_region():
    """พื้นที่ฝั่งกระเป๋าผู้เล่น (ซ้าย) ของหน้าต่างเกม เป็น (left, top, w, h)"""
    gx, gy, gw, gh = GAME_RECT
    x0, y0, x1, y1 = INVENTORY_REGION_FRAC
    return (int(gx + gw * x0), int(gy + gh * y0),
            int(gw * (x1 - x0)), int(gh * (y1 - y0)))


def wait_for_inventory_beef(timeout=TRUNK_STEP_TIMEOUT):
    """รอจนเจอเนื้อ A1 Beef ในฝั่งกระเป๋าผู้เล่น (ซ้าย) เท่านั้น
    ไม่สนเนื้อที่อยู่ฝั่งท้ายรถ (ขวา) ไม่เจอในเวลาที่กำหนดคืน None"""
    if GAME_RECT is None:
        return None

    region = inventory_region()
    end = time.time() + timeout

    while time.time() < end and not stop_event.is_set():
        box = find_one(BEEF, region, BEEF_INV_CONFIDENCE)

        if box is not None:
            return box

        wait(0.1)

    return None


def _max_template():
    # ตัดเฉพาะตัวปุ่ม MAX (ตัดพื้นหลัง/ขอบมนทิ้ง)
    tpl = load_template(MAX_BTN)
    return np.ascontiguousarray(tpl[18:112, 22:189])


def find_max_scaled():
    """หาปุ่ม MAX แบบหลายขนาด (รูป animal_max_button.png ใหญ่กว่าปุ่มจริงในเกมมาก)
    คืน (คะแนนที่ดีที่สุด, Box หรือ None, สเกลที่ดีที่สุด)"""
    if GAME_RECT is None:
        return 0.0, None, 0.0

    screen = grab_screen(GAME_RECT)
    base = _max_template()
    best = (0.0, None, 0.0)

    for sc in np.arange(0.15, 1.01, 0.05):
        w, h = int(base.shape[1] * sc), int(base.shape[0] * sc)

        if (w < 12 or h < 8 or w > screen.shape[1] or h > screen.shape[0]):
            continue

        tpl = cv2.resize(base, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
        _, score, _, loc = cv2.minMaxLoc(res)

        if score > best[0]:
            best = (float(score),
                    Box(GAME_RECT[0] + loc[0], GAME_RECT[1] + loc[1], w, h),
                    float(sc))

    return best


def wait_for_max(timeout=AFTER_DRAG_WAIT):
    end = time.time() + timeout
    best = (0.0, None, 0.0)

    while time.time() < end and not stop_event.is_set():
        cur = find_max_scaled()

        if cur[0] > best[0]:
            best = cur

        if cur[1] is not None and cur[0] >= MAX_CONFIDENCE:
            log(f"TRUNK: MAX คะแนน {cur[0]:.2f} สเกล {cur[2]:.2f}")
            return cur[1]

        wait(0.15)

    log(f"TRUNK: ไม่เจอ MAX (ดีที่สุด {best[0]:.2f} สเกล {best[2]:.2f} "
        f"ต้อง >= {MAX_CONFIDENCE})")
    return None


def log_scores(label, items):
    parts = []

    for name, path in items:
        m = _match(path, None)

        if m is not None:
            parts.append(f"{name} {cv2.minMaxLoc(m[0])[1]:.2f}")

    log(f"TRUNK [{label}] คะแนนที่เห็นบนจอ: {', '.join(parts)}")


def save_debug(name):
    try:
        if GAME_RECT is not None:
            left, top, w, h = GAME_RECT
            ImageGrab.grab(bbox=(left, top, left + w, top + h),
                           all_screens=True).save(str(BASE_DIR / name))
            log(f"TRUNK: บันทึกภาพหน้าจอไว้ที่ {name}")
    except Exception as e:
        log(f"save_debug ERROR: {e!r}")


def farm_menu_visible():
    # นับปุ่มซื้อด้วย: เมนูที่เปิดอยู่แต่ไม่มีสัตว์พร้อม จะเห็นแค่ปุ่มซื้อ
    return any(find_one(img, None, conf) is not None
               for img, conf in ((FEED, CONFIDENCE), (COLLECT, CONFIDENCE),
                                 (BUY, BUY_CONFIDENCE)))


def wait_farm_menu_closed(timeout=3):
    end = time.time() + timeout

    while time.time() < end and not stop_event.is_set():
        if not farm_menu_visible():
            return True

        wait(0.1)

    return not farm_menu_visible()


def trunk_ui_visible():
    return any(find_one(img, None, CONFIDENCE) is not None
               for img in (GARAGE_HEADER, CAR_CARD, OPEN_TRUNK, BEEF,
                           MAX_BTN, CONFIRM))


def close_trunk_windows():
    """กด CLOSE_KEY เฉพาะตอนที่ยังเห็นหน้าต่างโรงรถ/ท้ายรถอยู่
    (กัน Esc เปล่าๆ ไปเปิดเมนู Pause ของเกม)"""
    for _ in range(4):
        if stop_event.is_set() or not trunk_ui_visible():
            return True

        press_key(CLOSE_KEY)
        wait(0.5)

    return not trunk_ui_visible()


def reopen_farm_menu():
    for _ in range(2):
        if farm_menu_visible():
            return True

        press_key(OPEN_MENU_KEY)

        if wait_for(FEED, 3) is not None or farm_menu_visible():
            return True

    return farm_menu_visible()


def deposit_trip():
    """ปิดเมนูฟาร์ม -> E -> คลิกขวาการ์ดรถ -> Open Trunk -> ลากเนื้อไปท้ายรถ -> MAX
    -> Confirm -> ปิดหน้าต่าง -> เปิดเมนูฟาร์มกลับ  คืน True ถ้าสำเร็จ"""
    log("TRUNK: เริ่มฝากเนื้อ")

    # 1) ปิดเมนูฟาร์ม: ถ้าเห็นเมนู (ปุ่ม FEED/COLLECT/BUY) กด Esc ปิดก่อน
    if farm_menu_visible():
        press_key(CLOSE_KEY)

        if not wait_farm_menu_closed(3):
            log("TRUNK: เมนูฟาร์มไม่ปิดด้วย CLOSE_KEY -> ลองกด "
                f"{OPEN_MENU_KEY.upper()} แทน")
            press_key(OPEN_MENU_KEY)
            wait(0.5)

    # 2) E เปิดโรงรถ (ต้องยืนชิดตู้แดง)
    # เมนูฟาร์มอาจเปิดค้างโดยที่บอทมองไม่เห็นปุ่มสักตัว -> ถ้า E แล้วโรงรถไม่ขึ้น
    # ให้ลองกด Esc ปิดเมนูที่อาจบังอยู่ แล้วกด E ใหม่อีกครั้ง (ตัดสินจากว่าโรงรถเปิดได้ไหม)
    header = None

    for attempt in range(2):
        if stop_event.is_set():
            return False

        press_key(INTERACT_KEY)
        header = wait_for(GARAGE_HEADER, 2.5 if attempt == 0 else TRUNK_STEP_TIMEOUT)

        if header is not None:
            break

        if attempt == 0:
            log("TRUNK: กด E แล้วโรงรถไม่ขึ้น -> เมนูฟาร์มอาจเปิดค้างอยู่ "
                f"ลองกด {CLOSE_KEY.upper()} ปิดแล้วกด E ใหม่")
            press_key(CLOSE_KEY)
            wait(0.6)

    if header is None:
        log("TRUNK: ไม่เจอหน้าต่าง GARAGE VEHICLE -> ยืนชิดตู้แดงพอหรือยัง? "
            "(ต้องเห็นข้อความ 'E เปิดโรงรถ')")
        return False

    # 3) คลิกขวาการ์ดรถ
    card = wait_for(CAR_CARD)

    if card is None:
        log("TRUNK: ไม่เจอการ์ดรถ (รถอาจไม่ Ready / ชื่อไม่ตรงรูป animal_car_card.png)")
        close_trunk_windows()
        return False

    click_point(card.left + CAR_CLICK_OFFSET[0],
                card.top + CAR_CLICK_OFFSET[1], "right")

    # 4) Open Trunk
    opn = wait_for(OPEN_TRUNK)

    if opn is None:
        log("TRUNK: เมนูคลิกขวา (Open Trunk) ไม่ขึ้น")
        close_trunk_windows()
        return False

    click_box(opn)
    wait(TRUNK_UI_DELAY)

    # 5) ลากเนื้อจากกระเป๋า (ซ้าย) ไปช่องท้ายรถ (ขวา) -> MAX -> Confirm
    moved = False

    for attempt in range(1, DRAG_RETRIES + 1):
        # ค้นเฉพาะฝั่งกระเป๋าผู้เล่น (ซ้าย) ไม่หยิบเนื้อที่อยู่ในท้ายรถ (ขวา)
        beef = wait_for_inventory_beef()

        if beef is None:
            log("TRUNK: ไม่เจอเนื้อ A1 Beef ในกระเป๋าผู้เล่น (ฝั่งซ้าย) "
                "(ถ้าเนื้อในกระเป๋าหมดแล้ว หรือ INVENTORY_REGION_FRAC "
                "ไม่ครอบคลุมช่องกระเป๋า ก็จะเป็นแบบนี้)")
            save_debug("debug_no_beef.png")
            close_trunk_windows()
            return False

        log(f"TRUNK: ลากเนื้อจากกระเป๋า ({beef.left + beef.width // 2},"
            f"{beef.top + beef.height // 2}) ไปท้ายรถ "
            f"(ครั้งที่ {attempt}/{DRAG_RETRIES})")

        if not drag_box_to_frac(beef, TRUNK_DROP_FRAC):
            return False

        # หลังปล่อย เกมน่าจะเด้งกล่องใส่จำนวน (MAX / Confirm) ขึ้นมา
        mx = wait_for_max(AFTER_DRAG_WAIT)

        if mx is None:
            save_debug("debug_after_drag.png")

        if mx is not None:
            log("TRUNK: เจอปุ่ม MAX -> กด")
            click_box(mx)
            wait(TRUNK_UI_DELAY)

        conf = wait_for(CONFIRM, 2 if mx is not None else 1.0)

        if conf is not None:
            click_box(conf)
            moved = True
            break

        if mx is None:
            log("TRUNK: ลากแล้วไม่มีหน้าต่าง MAX/Confirm ขึ้น -> ลองลากใหม่")
        else:
            log("TRUNK: กด MAX แล้วแต่ไม่เจอปุ่ม Confirm -> ลองลากใหม่")

    if not moved:
        log("TRUNK: ลากเนื้อไม่สำเร็จ (ลองปรับ TRUNK_DROP_FRAC ให้ตรงช่องท้ายรถ "
            "หรือรัน CTRL+D ดูว่าเจอ MAX/CONFIRM ไหม)")
        close_trunk_windows()
        return False

    wait(0.6)

    full = (Path(TRUNK_FULL).exists()
            and find_one(TRUNK_FULL, None, CONFIDENCE) is not None)

    # 6) ปิดหน้าต่าง แล้วกลับไปฟาร์ม
    close_trunk_windows()

    if full:
        log("TRUNK: รถเต็มแล้ว")
        return "full"

    if not reopen_farm_menu():
        log("TRUNK: เปิดเมนูฟาร์มกลับไม่ได้")
        return False

    log("TRUNK: ฝากเนื้อเสร็จ -> กลับไปฟาร์มต่อ")
    return True


# ==============================
# TRUNK TEST - ข้ามฟาร์ม ทดสอบเฉพาะรอบฝากเนื้อ (คลิกจริง 1 รอบ)
# ==============================

def trunk_test_thread():
    global running, GAME_RECT

    if running:
        log("BOT RUNNING อยู่ -> กด STOP ก่อนแล้วค่อยทดสอบ")
        return

    stop_event.clear()
    running = True

    try:
        log("TRUNK TEST: ยืนชิดตู้แดงให้เห็น 'E เปิดโรงรถ' แล้วคลิกกลับเข้าเกม")
        log(f"จะเริ่มใน {START_DELAY} วินาที")

        if not wait(START_DELAY):
            return

        title, rect = foreground_window()
        log(f"ACTIVE WINDOW: '{title}'  {rect}")

        if CHECK_GAME_TITLE and not any(
                k in title.lower() for k in GAME_TITLE_KEYWORDS):
            log("หน้าต่างที่ active ไม่ใช่เกม -> ยกเลิก (ไม่คลิกอะไร)")
            return

        GAME_RECT = rect
        result = deposit_trip()
        log(f"TRUNK TEST RESULT: {result}  "
            "(True = ครบทุกขั้น / False = พลาด ดูข้อความ TRUNK ด้านบน)")

    except Exception as e:
        log(f"ERROR: {e!r}")

    finally:
        running = False
        log("BOT READY")


def trunk_test():
    threading.Thread(target=trunk_test_thread, daemon=True).start()


# ==============================
# MAIN BOT
# ==============================

def run_bot():
    global running, GAME_RECT

    try:
        log(f"START IN {START_DELAY} SECONDS")
        log("PLEASE CLICK FIVE M GAME WINDOW NOW")

        if not wait(START_DELAY):
            return

        title, rect = foreground_window()
        log(f"ACTIVE WINDOW: '{title}'  {rect}")

        if CHECK_GAME_TITLE and not any(
                k in title.lower() for k in GAME_TITLE_KEYWORDS):
            log("หน้าต่างที่ active ไม่ใช่เกม -> ยกเลิก (ไม่คลิกอะไร)")
            log("ให้คลิกที่หน้าต่างเกมหลังกด START "
                "หรือแก้ GAME_TITLE_KEYWORDS / CHECK_GAME_TITLE ด้านบนไฟล์")
            return

        GAME_RECT = rect

        menu_open = any(
            find_one(img, confidence=conf) is not None
            for img, conf in ((BUY, BUY_CONFIDENCE),
                              (FEED, CONFIDENCE),
                              (COLLECT, CONFIDENCE))
        )

        if menu_open:
            log("เมนูฟาร์มเปิดอยู่แล้ว -> ไม่กดปุ่มเปิดเมนูซ้ำ (กันมันปิด)")
        else:
            log(f"SENDING {OPEN_MENU_KEY.upper()} TO ACTIVE WINDOW")
            press_key(OPEN_MENU_KEY)
            log("KEY SENT")

        # ไม่ต้องรอเมนูเปิด: ลูปนี้สแกนต่อเนื่อง เจอปุ่มไหนก็กดทันที
        trips = 0

        while not stop_event.is_set():
            reason = farm_loop()

            if reason != "trip":
                break

            result = deposit_trip()

            if result is not True:
                if result == "full":
                    log("รถเต็ม -> จบการทำงาน")
                else:
                    log("ฝากเนื้อไม่สำเร็จ -> หยุดบอท (ดูข้อความ TRUNK ด้านบน)")

                break

            trips += 1
            log(f"TRUNK TRIPS: {trips}")

            if MAX_TRIPS and trips >= MAX_TRIPS:
                log(f"ฝากครบ {MAX_TRIPS} รอบแล้ว -> จบ")
                break

        if stop_event.is_set():
            log("BOT STOPPED")
        else:
            log("CYCLE FINISHED")

    except Exception as e:
        log(f"ERROR: {e!r}")

    finally:
        running = False
        log("BOT READY")


# ==============================
# START / STOP
# ==============================

def start():
    global running

    log(f"{KEY_START.upper()} PRESSED")

    if running:
        log("BOT ALREADY RUNNING")
        return

    stop_event.clear()
    running = True

    threading.Thread(target=run_bot, daemon=True).start()


def stop():
    if stop_event.is_set():
        return

    stop_event.set()
    log("STOP REQUESTED")


def test():
    threading.Thread(target=test_thread, daemon=True).start()


# ==============================
# PROGRAM START
# ==============================

if __name__ == "__main__":

    missing_images = [
        image for image in [BUY, FEED, COLLECT]
        if not Path(image).exists()
    ]

    if missing_images:
        print("MISSING IMAGES:")
        for image in missing_images:
            print(image)

        input("Press Enter to exit...")
        raise SystemExit

    missing_trunk = [i for i in TRUNK_IMAGES if not Path(i).exists()]

    if AUTO_TRUNK and missing_trunk:
        print("[WARN] ขาดรูปสำหรับระบบเก็บเนื้อเข้ารถ -> ปิด AUTO_TRUNK ไว้ก่อน:")
        for image in missing_trunk:
            print("   ", image)
        AUTO_TRUNK = False

    print("==============================")
    print("  FIVE M ANIMAL FARM BOT")
    print("==============================")
    print(f"{KEY_START.upper()} = START")
    print(f"{KEY_STOP.upper()} = STOP")
    print(f"{KEY_TEST.upper()} = TEST (หาปุ่มเจอไหม ไม่คลิก)")
    print(f"{KEY_TRUNK_TEST.upper()} = TRUNK TEST (ทดสอบเฉพาะฝากเนื้อ 1 รอบ)")
    print("FAILSAFE = MOVE MOUSE TOP LEFT (จอหลัก)")
    print("==============================")

    if not is_admin():
        print("[WARN] ไม่ได้รันแบบ Administrator -> ถ้า FiveM รันแบบ admin")
        print("[WARN] บอทจะกดปุ่ม/คลิกเข้าเกมไม่ได้ (Windows บล็อก)")

    keyboard.add_hotkey(KEY_START, start)
    keyboard.add_hotkey(KEY_STOP, stop)
    keyboard.add_hotkey(KEY_TEST, test)
    keyboard.add_hotkey(KEY_TRUNK_TEST, trunk_test)

    log("READY - รอกดปุ่ม")

    keyboard.wait()