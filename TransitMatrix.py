# TransitMatrix.py
# Contact Fluffy_Nardoragon@mail.de or https://github.com/alfi-floof/TransitMatrix/issues
import base64
import ctypes
import functools
import hmac
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import atexit
import tkinter as tk
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from ctypes import wintypes
from datetime import datetime, timedelta
from hashlib import sha1

import config
from font import FONT
try:
    import credentials
except ModuleNotFoundError:
    print("=" * 60)
    print("ERROR : credentials.py not found!")
    print("Please rename :")
    print("credentials.py.example to:")
    print("'credentials.py'")
    print("Then enter your API credentials and start TransitMatrix again.")
    print("=" * 60)
    sys.exit('ERROR : credentials.py not found')

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
except ImportError:
    RGBMatrix = None
    RGBMatrixOptions = None

# Flush print output immediately
print = functools.partial(print, flush=True)

def debug_print(*args, **kwargs):
    if config.DEBUG:
        print(*args, **kwargs)

# ==========================
# Colors
# ==========================

def get_line_color(line_name):
    line_name = line_name.upper().strip()

    for prefix, color in config.LINE_COLORS.items():
        if line_name.startswith(prefix):
            return color

    return config.ColorCode.DEFAULT


# HEX → RGB for LED Matrix
def hex_to_rgb(hex_color):

    hex_color = hex_color.lstrip("#")

    return tuple(
        int(hex_color[i:i+2],16)
        for i in (0,2,4)
    )

# GLOBAL DATA

bus_data = []

db_train_cache = {}
db_fchg_cache = {}
db_plan_cache = {}

db_cache_lock = threading.Lock()

# Announcement line cache
announcement_line_cache = {}
announcement_line_cache_lock = threading.Lock()

station_names = []

show_station_header = False

messages = []
line_announcements = []
data_status = "OK"

scroll_offset = [0,0,0,0,0,0,0]

scroll_wait = [0,0,0,0,0,0,0]

line_scroll_offset = [0,0,0,0,0,0,0]
line_scroll_wait = [0,0,0,0,0,0,0]

time_scroll_offset = [0,0,0,0,0,0,0]

message_scroll_offset = 0
current_message = 0

blink_state = True
time_display_mode = 0
#0 = Planed Time | 1 = Delay | 2 = Minutes
now_lines = set()

window = None
canvas = None
led_canvas = None
matrix_led = None
has_delay = False
no_departures_blink = True
needs_render = False
current_brightness = None
target_time = None

reload_progress = config.WIDTH
last_update_time = time.time()
last_reload_time = 0
reload_start_time = time.time()
next_reload_pixel_time = time.time()

def get_signature(body):

    key = credentials.HVV_API_PASSWORD.encode("utf-8")

    hashed = hmac.new(
        key,
        body.encode("utf-8"),
        sha1
    )

    return base64.b64encode(
        hashed.digest()
    ).decode("utf-8")

def disable_rounded_corners(tk_window):
    if sys.platform != "win32":
        return

    try:
        # HWND returned by Tk
        tk_hwnd = wintypes.HWND(tk_window.winfo_id())

        # Get the actual top-level window HWND
        GA_ROOT = 2

        user32 = ctypes.windll.user32
        hwnd = user32.GetAncestor(
            tk_hwnd,
            GA_ROOT
        )

        if not hwnd:
            print("Could not get top-level HWND.")
            return

        print(f"Tk HWND:    {hex(tk_hwnd.value)}")
        print(f"Root HWND:  {hex(hwnd)}")

        # Windows 11 DWM settings
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1

        value = wintypes.DWORD(DWMWCP_DONOTROUND)

        dwmapi = ctypes.windll.dwmapi

        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD
        ]

        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

        result = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value),
            ctypes.sizeof(value)
        )

        if result == 0:
            print("Rounded corners disabled.")
        else:
            print(
                f"DwmSetWindowAttribute failed: "
                f"{result:#010x}"
            )

    except Exception as e:
        print(
            "Could not disable window corners:",
            repr(e)
        )

def cycle_window_title():
    titles = [
        "TransitMatrix",
        "github.com/alfi-floof",
        "Fluffy_Nardoragon@mail.de",
        "TransitMatrix"
    ]

    current = getattr(window, "_title_index", 0)

    window.title(titles[current])

    window._title_index = (current + 1) % len(titles)

    window.after(2000, cycle_window_title)

def create_window():
    global window
    global canvas
    if config.DISPLAY_MODE != "WINDOW":
        return

    window = tk.Tk()
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv[0] else os.getcwd()

    icon_path = os.path.join(script_dir, "icon.ico")

    try:
        icon_img = tk.PhotoImage(file=icon_path)
        window.tk.call("wm", "iconphoto", window._w, icon_img)
    except Exception as e:
        try:
            window.iconbitmap(icon_path)
        except Exception:
            pass

    window.title("TransitMatrix")
    window.after(2000, cycle_window_title)
    window.tk.call("tk", "scaling", 1.0)

    canvas = tk.Canvas(
        window,
        width=config.WIDTH * config.SCALE,
        height=config.HEIGHT * config.SCALE,
        bg="black",
        highlightthickness=0,
        bd=0,
    )
    canvas.pack(fill="none", expand=False)
    window.resizable(False, False)
    window.geometry(f"{config.WIDTH * config.SCALE}x{config.HEIGHT * config.SCALE}")

    def start_move(event):
        window._start_x = event.x
        window._start_y = event.y

    def do_move(event):
        deltax = event.x - getattr(window, "_start_x", 0)
        deltay = event.y - getattr(window, "_start_y", 0)
        x = window.winfo_x() + deltax
        y = window.winfo_y() + deltay
        window.geometry(f"+{x}+{y}")

    window.bind("<Button-1>", start_move)
    window.bind("<B1-Motion>", do_move)
    canvas.bind("<Button-1>", start_move)
    canvas.bind("<B1-Motion>", do_move)
    window.update_idletasks()
    disable_rounded_corners(window)
    window.update()

    def start_move(event):
        window._start_x = event.x
        window._start_y = event.y

    def do_move(event):
        deltax = event.x - getattr(window, "_start_x", 0)
        deltay = event.y - getattr(window, "_start_y", 0)

        x = window.winfo_x() + deltax
        y = window.winfo_y() + deltay

        window.geometry(f"+{x}+{y}")

    window.bind("<Button-1>", start_move)
    window.bind("<B1-Motion>", do_move)
    canvas.bind("<Button-1>", start_move)
    canvas.bind("<B1-Motion>", do_move)

    # Make sure the native window exists
    window.update_idletasks()

    # Disable Windows 11 rounded corners (wird unter Linux automatisch übersprungen/ignoriert)
    disable_rounded_corners(window)

    window.update()

# PIXEL MATRIX

def create_matrix():

    return [
        [0 for x in range(config.WIDTH)]
        for y in range(config.HEIGHT)
    ]

def set_pixel(matrix, x, y, color):

    if 0 <= x < config.WIDTH and 0 <= y < config.HEIGHT:
        matrix[y][x] = color

def show_matrix(matrix):

    if config.DISPLAY_MODE == "WINDOW":

        canvas.delete("all")

        for y,row in enumerate(matrix):

            x=0

            while x < config.WIDTH:

                if row[x]:

                    start = x

                    color = config.HEX_COLORS.get(row[x], config.HEX_COLORS[config.ColorCode.DEFAULT])

                    value = row[x]

                    while x < config.WIDTH and row[x] == value:
                        x += 1

                    canvas.create_rectangle(
                        start * config.SCALE,
                        y * config.SCALE,
                        x * config.SCALE,
                        (y + 1) * config.SCALE,
                        fill=color,
                        outline=""
                    )

                else:
                    x += 1

        window.update()


    elif config.DISPLAY_MODE == "LED":

        show_led(matrix)
# TERMINAL OUTPUT

def print_terminal(data):

    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)

    print("="*67)

    print(
        f"{'LINIE':<8}"
        f"{'ZIEL':<30}"
        f"{'PLAN':<10}"
        f"{'ZEIT':<12}"
        f"{'DELAY':<8}"
    )

    print("="*67)

    for bus in data:

        print(
            f"{bus.get('linie',''):<8}"
            f"{bus.get('ziel','')[:29]:<30}"
            f"{bus.get('plan',''):<10}"
            f"{bus.get('zeit',''):<12}"
            f"{(
            "+" + str(bus.get('delay',0))
    if bus.get('delay_found')
    else '-'
): <8}"
        )

    print("="*67)

def remove_duplicates(data):

    result = []
    seen = set()

    for bus in data:

        key = (
            bus.get("linie"),
            bus.get("ziel"),
            bus.get("plan"),
            bus.get("zeit")
        )

        if key not in seen:
            seen.add(key)
            result.append(bus)

    return result

def draw_char(matrix,x,y,char,color=1):

    char=normalize(char)

    if char not in FONT:
        char="?"

    bitmap=FONT[char]

    for yy,row in enumerate(bitmap):
        for xx,pixel in enumerate(row):

            if pixel=="1":

                for sx in range(config.FONT_SCALE):
                    for sy in range(config.FONT_SCALE):

                        set_pixel(
                            matrix,
                            x + xx * config.FONT_SCALE + sx,
                            y + yy * config.FONT_SCALE + sy,
                            color
                        )

def draw_text(matrix, x, y, text, color=1):

    for char in text:

        draw_char(
            matrix,
            x,
            y,
            char,
            color
        )

        if char == "'":
            x += config.CHAR_WIDTH + 1
        else:
            x += config.CHAR_WIDTH


def get_text_width(text):

    width = 0

    for c in text:
        if c == "'":
            width += config.CHAR_WIDTH + 1
        else:
            width += config.CHAR_WIDTH

    return width

def get_scroll_text(text,offset,length):


    text=normalize(text)


    if len(text)<=length:

        return text

    text += "   "


    pos=offset % len(text)


    return (
        text[pos:]
        +
        text[:pos]
    )[:length]


def draw_bus_block(matrix, index, bus):
    global blink_state
    if not bus:
        return

    y_line = index * 16
    y_target = y_line + 8
    line = normalize(bus.get("linie", ""))

    time_reserved = 5 * config.CHAR_WIDTH
    line_pixel_space = config.WIDTH - time_reserved
    max_line_chars = line_pixel_space // config.CHAR_WIDTH

    if get_text_width(line) > line_pixel_space:
        line_display = get_scroll_text(line, line_scroll_offset[index], max_line_chars)
    else:
        line_display = line

    line_color = get_line_color(line)
    ziel = normalize(bus.get("ziel", ""))
    plan_time_clean = re.sub(r"\s*\+\s*\d+", "", bus.get("plan", "")).strip()
    zeit_raw = bus.get("zeit", "")
    delay = bus.get("delay", 0)
    delay_found = bus.get("delay_found", False)

    is_logo_line = re.match(r"^(S|U|A)(?:\d+)?$", line.strip(), re.IGNORECASE)

    if is_logo_line:
        draw_text(matrix, 0, y_line, line_display[0], line_color)
        draw_text(matrix, config.CHAR_WIDTH, y_line, line_display[1:], config.ColorCode.DEFAULT)
    else:
        draw_text(matrix, 0, y_line, line_display, line_color)

    # =====================
    # MINUTES & "NOW" LOGIC
    # =====================
    display_minutes = ""
    zeit_lower = normalize(zeit_raw).lower()
    is_cancelled = "fällt aus" in zeit_lower
    api_now = ("sofort" in zeit_lower or "jetzt" in zeit_lower or "now" in zeit_lower or re.search(r"\bin\s*0\s*min\b", zeit_lower) is not None)
    now_active = api_now
    target_time_bus = bus.get("target_time")

    if not is_cancelled and not api_now and target_time_bus:
        diff_seconds = (target_time_bus - datetime.now()).total_seconds()
        minutes = math.ceil(diff_seconds / 60)
        if minutes <= 0:
            now_active = True
        elif minutes == 1:
            display_minutes = "1'"
        else:
            display_minutes = str(minutes) + "'"
    elif not is_cancelled and not now_active:
        match = re.search(r"\b(?:in\s*)?(\d+)\s*Min", zeit_raw, re.IGNORECASE)
        if match:
            minutes = int(match.group(1))
            if minutes <= 0:
                now_active = True
            elif minutes == 1:
                display_minutes = "1'"
            else:
                display_minutes = str(minutes) + "'"

    if is_cancelled:
        display_minutes = "AUS"
    elif now_active:
        display_minutes = "NOW"

    # =====================
    # TIME ON THE RIGHT
    # =====================
    if now_active:
        now_text = "NOW" if blink_state else "   "
        time_x = config.WIDTH - get_text_width(now_text) + 1
        draw_text(matrix, time_x, y_line, now_text, config.ColorCode.DEFAULT)
    elif display_minutes == "AUS":
        cancel_text = "FÄLLT" if blink_state else "AUS"
        time_x = config.WIDTH - get_text_width(cancel_text) + 1
        draw_text(matrix, time_x, y_line, cancel_text, config.ColorCode.DELAY)
    elif time_display_mode == 0:
        time_x = config.WIDTH - get_text_width(plan_time_clean)
        draw_text(matrix, time_x, y_line, plan_time_clean, config.ColorCode.DEFAULT)
    else:
        if time_display_mode == 1 and delay_found:
            right_text = "+" + str(delay) + "'"
            color = config.ColorCode.DELAY if delay > 0 else config.ColorCode.OK
        else:
            right_text = display_minutes
            color = config.ColorCode.DEFAULT

        time_width = get_text_width(right_text)
        time_x = max(30, config.WIDTH - time_width)
        draw_text(matrix, time_x, y_line, right_text, color)

    # =====================
    # DESTINATION BOTTOM
    # =====================
    show_ring = ziel in ("RING S41", "RING S42")
    max_chars = 8 if show_ring else 10
    target_display = get_scroll_text(ziel, scroll_offset[index], max_chars)
    draw_text(matrix, 0, y_target, target_display, config.ColorCode.DEFAULT)

    if has_line_announcement(bus):
        draw_text(matrix, config.WIDTH - get_text_width("!"), y_target, "!", config.ColorCode.DELAY)

    if show_ring:
        symbol_x = get_text_width(target_display) + 2
        s41_bitmap = ["0011100", "0100010", "1000111", "1000010", "1000000", "0100010", "0011100"]
        s42_bitmap = ["0011100", "0100010", "1110001", "0100001", "0000001", "0100010", "0011100"]
        bitmap = s41_bitmap if ziel == "RING S41" else s42_bitmap
        for yy, row in enumerate(bitmap):
            for xx, pixel in enumerate(row):
                if pixel == "1":
                    px, py = symbol_x + xx, y_target + yy
                    if 0 <= px < config.WIDTH and 0 <= py < config.HEIGHT:
                        set_pixel(matrix, px, py, config.ColorCode.DEFAULT)

def is_platform(text):

    text = text.strip().upper()

    if re.fullmatch(r"\d+", text):
        return True

    if re.fullmatch(r"\d+[A-Z]", text):
        return True

    if re.fullmatch(r"\d+\s*[A-Z](?:-[A-Z])?", text):
        return True

    if re.fullmatch(r"[A-Z]\d+", text):
        return True

    if re.fullmatch(r"[A-Z]", text):
        return True

    if re.fullmatch(
            r"(GLEIS|STEIG|BAHNSTEIG|BSTG\.?)\s*[A-Z0-9+-]+(?:\s*\([A-Z]+\))?",
            text,
            re.IGNORECASE
    ):
        return True

    if re.fullmatch(
            r"(?:BSTG\.?\s*)?\d+\s+[A-ZÄÖÜ]+",
            text,
            re.IGNORECASE):
        return True

    return False

def is_line(text):

    text = text.strip().upper()

    if text in [
        "ABFAHRT",
        "LINIE",
        "ZIEL",
        "RICHTUNG",
        "PLANZEIT"
    ]:
        return False

    if not text:
        return False

    if (
        "MIN" in text
        or "SOFORT" in text
        or "JETZT" in text
    ):
        return False

    if re.fullmatch(
            r"[A-ZÄÖÜ]+(?:/[A-ZÄÖÜ]+)?\s*\d+",
            text
    ):
        return True

    # LINES LIKE E/525, H/123, X/45
    if re.fullmatch(
            r"[A-ZÄÖÜ]+/\d+",
            text
    ):
        return True


    # Normal Lines
    if re.fullmatch(
                r"(MEX|ALX|FLX|FEX|ICE|ECE|IRE|ZUG|AST|KAT|SCH|SEV|RNV|AT|CB|RS|RE|RB|RJ|NJ|EN|GI|IC|IR|LM|EC|EV|FM|SB|TB|HS|S|U|A|C|X|M|N|R|F)(?:[\s-]*([A-Z]*\d+))?",
            text
    ):
        return True

    # normal Buslines (z.B. 782, 501, 12)
    if re.fullmatch(
            r"[A-ZÄÖÜ]*\d+[A-ZÄÖÜ]*",
            text
    ):
        return True

    return False

# ============================================================
# DB TIMETABLE TEMP FILE MANAGEMENT
# ============================================================

DB_TIMETABLE_PATTERN = "db_timetable_*.xml"

def cleanup_db_timetable_files():
    try:
        # Attempt to use __file__ first (works when run as a standard script)
        script_dir = Path(__file__).resolve().parent
    except NameError:
        # Fallback for environments where __file__ is undefined (e.g., some IDEs or compiled executables)
        script_dir = Path(sys.argv[0]).resolve().parent if sys.argv[0] else Path.cwd()

    for path in script_dir.glob(DB_TIMETABLE_PATTERN):
        try:
            if path.is_file():
                path.unlink()
                debug_print("Removed DB timetable file:", path.name)
        except Exception as e:
            debug_print(f"Could not remove DB timetable file {path.name}: {e}")


def parse_db_train_by_time(data, category, train_number, planned_departure, destination=None, time_tolerance_minutes=15):
    if not data:
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None

    wanted_category = normalize(category).upper()
    wanted_number = str(train_number).strip()
    wanted_destination = normalize(destination or "").upper()

    # Long-distance train category aliases in DB IRIS
    LONG_DISTANCE_CATS = {"ICE", "IC", "EC", "ECE", "RJ", "RJX", "TGV", "FLX", "DPF", "D"}

    best_match = None
    best_score = None

    for service in root.iter():
        if service.tag.split("}")[-1].lower() != "s":
            continue

        tl, dp, ar = None, None, None
        for child in service:
            c_tag = child.tag.split("}")[-1].lower()
            if c_tag == "tl":
                tl = child
            elif c_tag == "dp":
                dp = child
            elif c_tag == "ar":
                ar = child

        if tl is None:
            continue

        c = tl.get("c", "").strip().upper()
        n = tl.get("n", "").strip()

        # 1. Match train number
        if n != wanted_number:
            continue

        # 2. Match category flexibly for long-distance trains
        if wanted_category in LONG_DISTANCE_CATS:
            if c not in LONG_DISTANCE_CATS:
                continue
        else:
            if c != wanted_category:
                continue

        event = dp if dp is not None else ar
        if event is None:
            continue

        db_time = event.get("ct", "").strip() or event.get("pt", "").strip()
        if not db_time:
            continue

        try:
            db_departure = datetime.strptime(db_time, "%y%m%d%H%M")
        except ValueError:
            continue

        diff_secs = abs((db_departure - planned_departure).total_seconds())

        # Allow wider time window for long-distance trains (e.g., 60 mins)
        max_tolerance = 60 if wanted_category in LONG_DISTANCE_CATS else time_tolerance_minutes
        if diff_secs > max_tolerance * 60:
            continue

        dest_match = False
        if wanted_destination:
            texts = [
                normalize(child.text.strip()).upper()
                for child in service.iter()
                if child.text and child.tag.split("}")[-1].lower() in ("n", "name", "destination", "station", "dp", "ar")
            ]
            dt = " ".join(texts)
            if wanted_destination in dt or any(w in dt for w in wanted_destination.split() if len(w) >= 4):
                dest_match = True

        score = (0 if dest_match else 1, diff_secs)
        if best_score is None or score < best_score:
            best_score = score
            best_match = f"{c} {n}"

    return best_match

def find_db_train_by_time(
    data,
    category,
    planned_departure,
    destination=None,
    time_tolerance_minutes=2
):
    """
    Find a DB train when HVV only provides a category,
    e.g. ICE, IC, FLX or DPF.

    The train number is taken from the DB timetable.
    """

    if not data:
        return None

    try:

        root = ET.fromstring(data)

    except ET.ParseError as e:

        print(
            "DB Timetable XML Error:",
            repr(e)
        )

        return None

    wanted_category = normalize(
        category
    ).upper()

    wanted_destination = normalize(
        destination or ""
    ).upper()

    best_match = None
    best_score = None

    for service in root.iter():

        tag = (
            service.tag
            .split("}")[-1]
            .lower()
        )

        if tag != "s":
            continue

        tl = None
        dp = None
        ar = None

        for child in service:

            child_tag = (
                child.tag
                .split("}")[-1]
                .lower()
            )

            if child_tag == "tl":
                tl = child

            elif child_tag == "dp":
                dp = child

            elif child_tag == "ar":
                ar = child

        if tl is None:
            continue

        train_category = (
            tl.get("c", "")
            .strip()
            .upper()
        )

        train_number = (
            tl.get("n", "")
            .strip()
        )

        if not train_number:
            continue

        # ==================================================
        # CATEGORY
        # ==================================================

        if wanted_category == "DPF":

            if train_category not in (
                "DPF",
                "FLX",
                "IC",
                "ICE"
            ):
                continue

        else:

            if train_category != wanted_category:
                continue

        # ==================================================
        # TIME
        # ==================================================

        event = (
            dp
            if dp is not None
            else ar
        )

        if event is None:
            continue

        db_time = (
            event.get("ct", "").strip()
            or event.get("pt", "").strip()
        )

        if not db_time:
            continue

        try:

            db_departure = datetime.strptime(
                db_time,
                "%y%m%d%H%M"
            )

        except ValueError:

            continue

        difference_seconds = abs(
            (
                db_departure
                - planned_departure
            ).total_seconds()
        )

        if (
            difference_seconds
            > time_tolerance_minutes * 60
        ):
            continue

        # ==================================================
        # DESTINATION
        # ==================================================

        destination_match = False

        if wanted_destination:

            texts = []

            for child in service.iter():

                text = (
                    child.text.strip()
                    if child.text
                    else ""
                )

                if not text:
                    continue

                child_tag = (
                    child.tag
                    .split("}")[-1]
                    .lower()
                )

                if child_tag in (
                    "n",
                    "name",
                    "destination",
                    "station",
                    "dp",
                    "ar"
                ):

                    texts.append(
                        normalize(text).upper()
                    )

            destination_text = " ".join(texts)

            if wanted_destination in destination_text:

                destination_match = True

            else:

                words = [
                    word
                    for word in wanted_destination.split()
                    if len(word) >= 4
                ]

                if words and all(
                    word in destination_text
                    for word in words
                ):

                    destination_match = True

        score = (
            0 if destination_match else 1,
            difference_seconds
        )

        if (
            best_score is None
            or score < best_score
        ):

            best_score = score

            best_match = (
                f"{train_category} "
                f"{train_number}"
            )

    return best_match

def lookup_db_train_by_time(
    station_id,
    category,
    train_number,
    planned_departure,
    destination
):
    """
    Look up a specific DB train.

    Search order:
        1. planned timetable, same hour
        2. previous hour
        3. next hour
        4. full changes feed

    Result is cached.
    """

    category = normalize(category).upper()
    train_number = str(train_number).strip()
    destination = normalize(destination or "")

    if not train_number:
        return None

    cache_key = (
        "NUMBER",
        category,
        train_number,
        destination.upper(),
        planned_departure.strftime(
            "%y%m%d%H%M"
        )
    )

    with db_cache_lock:

        cached = db_train_cache.get(
            cache_key
        )

        if cached:

            age = (
                time.time()
                - cached["timestamp"]
            )

            if age < config.DB_CACHE_TIME:

                debug_print(
                    f"DB Cache HIT: "
                    f"{category} {train_number}"
                )

                return cached.get("data")

    # ==================================================
    # EVA
    # ==================================================

    eva = getattr(
        config,
        "DB_STATION_EVA",
        None
    )

    if not eva:

        eva = get_db_station_eva(
            config.STATION_NAME
        )

    if not eva:

        print(
            f"No DB EVA number available for "
            f"'{config.STATION_NAME}'."
        )

        return None

    eva = str(eva).strip()

    # ==================================================
    # HOURS TO CHECK
    # ==================================================

    hours_to_check = [
        planned_departure - timedelta(hours=1),
        planned_departure,
        planned_departure + timedelta(hours=1)
    ]

    checked = set()
    result = None

    for check_time in hours_to_check:

        key = (
            check_time.strftime("%y%m%d"),
            check_time.hour
        )

        if key in checked:
            continue

        checked.add(key)

        data = get_db_plan(
            eva,
            key[0],
            key[1]
        )

        if not data:
            continue

        result = parse_db_train_by_time(
            data,
            category,
            train_number,
            planned_departure,
            destination=destination
        )

        if result:
            break

    # ==================================================
    # FCHG FALLBACK
    # ==================================================

    if result is None:

        print(
            f"DB Schedule: no match for "
            f"{category} {train_number} "
            f"at {planned_departure.strftime('%H:%M')}"
        )

        change_data = get_db_changes(eva)

        if change_data:

            result = parse_db_change_by_time(
                change_data,
                category,
                planned_departure,
                destination=destination
            )

            # Make sure fchg didn't return a different train number.
            if result:

                result_category, _, result_number = (
                    result.partition(" ")
                )

                if result_number != train_number:

                    debug_print(
                        "DB FCHG returned different train:",
                        result
                    )

                    result = None

    # ==================================================
    # CACHE
    # ==================================================

    with db_cache_lock:

        db_train_cache[cache_key] = {
            "timestamp": time.time(),
            "data": result
        }

    if result:

        print(
            f"DB train found: "
            f"{result} "
            f"(at {planned_departure.strftime('%H:%M')})"
        )

    else:

        print(
            f"DB train not found: "
            f"{category} {train_number} "
            f"um {planned_departure.strftime('%H:%M')}"
        )

    return result

def check_station_defined():
    global data_status

    invalid_placeholders = {"", "YOUR_STATION_ID", "YOUR_STATION_NAME", "NONE", "0"}

    # Safely retrieve values from config
    station_id = getattr(config, "STATION_ID", None)
    station_name = getattr(config, "STATION_NAME", None)

    # Sanitize inputs
    id_str = str(station_id).strip().upper() if station_id is not None else ""
    name_str = str(station_name).strip().upper() if station_name is not None else ""

    # Determine validity
    has_valid_id = bool(id_str) and id_str not in invalid_placeholders
    has_valid_name = bool(name_str) and name_str not in invalid_placeholders

    # Valid if EITHER station_id OR station_name (or both) is configured
    if has_valid_id or has_valid_name:
        return True

    data_status = "NO_STATION"
    return False

def get_hvv_data():
    global data_status
    if not check_station_defined():
        data_status = "NO_STATION"
        return [{"linie": "", "ziel": "NO STATION", "plan": "", "zeit": "", "nodata": True}]

    url = config.HVV_API_URL.rstrip("/") + "/gti/public/departureList"
    now = datetime.now()
    station_id = str(config.STATION_ID).strip()
    station_name = str(config.STATION_NAME).strip()

    payload = {
        "language": "de",
        "version": 63,
        "station": {"id": station_id, "name": station_name, "type": "STATION"},
        "time": {"date": now.strftime("%d.%m.%Y"), "time": now.strftime("%H:%M")},
        "maxList": 10,
        "maxTimeOffset": 1440,
        "useRealtime": True,
        "full": True,
        "showBroadcastRelevant": True
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    headers = {
        "geofox-auth-user": credentials.HVV_API_USER,
        "geofox-auth-signature": get_signature(body),
        "geofox-auth-type": "HmacSHA1",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "TransitMatrix"
    }
    request = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"HVV API Error: {e}")
        return [{"linie": "", "ziel": "API ERROR", "plan": "", "zeit": "", "nodata": True}]

    result = []
    for dep in data.get("departures", []):
        # DELAY
        delay_seconds = dep.get("delay")
        if delay_seconds is not None:
            try:
                delay = int(int(delay_seconds) / 60)
            except (TypeError, ValueError):
                delay = 0
            delay_found = True
        else:
            delay = 0
            delay_found = False

        # TIME OFFSET (Realtime offset from now)
        try:
            offset = int(dep.get("timeOffset", 0))
        except (TypeError, ValueError):
            offset = 0

        # Filter out trains that departed more than 1 minute ago
        if offset < -1 and not dep.get("cancelled"):
            continue

        target_time = now + timedelta(minutes=offset)
        planned_departure = target_time - timedelta(minutes=delay)
        plan_time = planned_departure.strftime("%H:%M")

        if offset <= 0:
            zeit = "sofort"
        else:
            zeit = f"in {offset} Min"
        if dep.get("cancelled"):
            zeit = "fällt aus"

        # LINE EXTRACT & DIRECTION
        line = dep.get("line", {})
        line_name = str(line.get("name", "")).strip()
        line_direction = str(line.get("direction", "")).strip()

        # Extract Category & Train Number (handles "ICE 582", "ICE582", "RE 80", etc.)
        match = re.match(r"^([A-Za-z]+)\s*(\d+)$", line_name)
        if match:
            category = match.group(1).upper()
            train_number = match.group(2)
        else:
            parts = line_name.split()
            category = parts[0].upper() if parts else ""
            train_number = parts[1] if len(parts) > 1 else ""

        # ==========================================
        # DB TIMETABLE CROSS-REFERENCE LOGIC
        # ==========================================
        db_categories = {
            "ICE",
            "IC",
            "EC",
            "ECE",
            "RE",
            "RB",
            "IRE",
            "FLX",
            "DPF"
        }

        if category in db_categories and not train_number:

            try:

                db_match = lookup_db_train_without_number(
                    category=category,
                    planned_departure=planned_departure,
                    destination=line_direction
                )

                if db_match:
                    line_name = db_match

            except Exception as e:

                debug_print(
                    f"DB lookup failed for "
                    f"{category}: {e}"
                )
        result.append({
            "station": {"id": station_id, "name": station_name},
            "linie": line_name,
            "ziel": line_direction,
            "plan": plan_time,
            "zeit": zeit,
            "delay": delay,
            "delay_found": delay_found,
            "target_time": target_time
        })

    # Sort final result chronologically by the true target realtime
    result.sort(key=lambda x: x["target_time"])
    return result

def lookup_db_train_without_number(
    category,
    planned_departure,
    destination
):
    """
    Find a DB train when HVV only provides the category.

    Example:
        HVV -> ICE
        DB  -> ICE 123

    Searches:
        previous hour
        current hour
        next hour
        /fchg fallback
    """

    category = normalize(category).upper()
    destination = normalize(destination or "")

    cache_key = (
        "WITHOUT_NUMBER",
        category,
        destination.upper(),
        planned_departure.strftime(
            "%y%m%d%H%M"
        )
    )

    with db_cache_lock:

        cached = db_train_cache.get(
            cache_key
        )

        if cached:

            age = (
                time.time()
                - cached["timestamp"]
            )

            if age < config.DB_CACHE_TIME:

                debug_print(
                    f"DB Cache HIT: "
                    f"{category} "
                    f"{planned_departure.strftime('%H:%M')}"
                )

                return cached.get("data")

    # ==================================================
    # EVA
    # ==================================================

    eva = getattr(
        config,
        "DB_STATION_EVA",
        None
    )

    if not eva:

        eva = get_db_station_eva(
            config.STATION_NAME
        )

    if not eva:

        print(
            f"DB: No EVA-Number for "
            f"{config.STATION_NAME}"
        )

        return None

    eva = str(eva).strip()

    print(
        f"DB search without train number: "
        f"{category} | "
        f"{planned_departure.strftime('%d.%m.%Y %H:%M')} | "
        f"Ziel: {destination} | "
        f"EVA: {eva}"
    )

    result = None

    # ==================================================
    # PLAN
    # ==================================================

    hours_to_check = [
        planned_departure - timedelta(hours=1),
        planned_departure,
        planned_departure + timedelta(hours=1)
    ]

    checked = set()

    for check_time in hours_to_check:

        key = (
            check_time.strftime("%y%m%d"),
            check_time.hour
        )

        if key in checked:
            continue

        checked.add(key)

        data = get_db_plan(
            eva,
            key[0],
            key[1]
        )

        if not data:
            continue

        result = find_db_train_by_time(
            data,
            category,
            planned_departure,
            destination
        )

        if result:
            break

    # ==================================================
    # FCHG
    # ==================================================

    if result is None:

        print(
            f"DB Plan: No {category}-Hit for "
            f"{planned_departure.strftime('%H:%M')}"
        )

        change_data = get_db_changes(eva)

        if change_data:

            result = parse_db_change_by_time(
                change_data,
                category,
                planned_departure,
                destination=destination
            )

    # ==================================================
    # CACHE
    # ==================================================

    with db_cache_lock:

        db_train_cache[cache_key] = {
            "timestamp": time.time(),
            "data": result
        }

    if result:

        print(
            f"DB Mapping without HVV-Number: "
            f"{category} -> {result}"
        )

    else:

        print(
            f"DB Train not found: "
            f"{category} "
            f"um {planned_departure.strftime('%H:%M')}"
        )

    return result

def is_long_distance_train(line):
    line = normalize(line)

    return bool(re.fullmatch(
        r"(ICE|IC|DPF|FLX)\s*\d+",
        line
    ))

def db_api_get(path):
    """
    Perform a GET request against the DB Timetables API.

    The DB API uses:
        DB-Client-ID
        DB-Api-Key

    Returns:
        bytes
        or None on failure
    """

    base_url = config.DB_API_URL.rstrip("/")
    clean_path = "/" + path.lstrip("/")

    url = base_url + clean_path

    client_id = str(
        getattr(credentials, "DB_TIMETABLES_CLIENT_ID", "")
    ).strip()

    api_key = str(
        getattr(credentials, "DB_TIMETABLES_API_KEY", "")
    ).strip()

    if not client_id or not api_key:
        print(
            "DB API credentials missing. "
            "Check credentials.py."
        )
        return None

    headers = {
        "DB-Client-ID": client_id,
        "DB-Api-Key": api_key,
        "Accept": "application/xml",
        "User-Agent": "TransitMatrix/1.0"
    }

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            data = response.read()

            print(
                f"DB HTTP {response.status}: "
                f"{response.geturl()}"
            )

            print(
                "DB Content-Type:",
                response.headers.get("Content-Type", "")
            )

            print(
                "DB Response length:",
                len(data),
                "bytes"
            )

            if config.DEBUG:
                try:
                    debug_file = (
                        Path(__file__).resolve().parent
                        / "db_timetable_debug.xml"
                    )

                    debug_file.write_bytes(data)

                    debug_print(
                        "DB debug XML written:",
                        debug_file.name
                    )

                except OSError as e:
                    debug_print(
                        "Could not write DB debug XML:",
                        repr(e)
                    )

            debug_print(
                "DB Response:",
                data[:500]
            )

            return data

    except urllib.error.HTTPError as e:

        try:
            error_body = e.read().decode(
                "utf-8",
                errors="replace"
            )
        except Exception:
            error_body = ""

        print(
            f"DB Timetables HTTP Error "
            f"{e.code}: {url}"
        )

        if error_body:
            debug_print(
                "DB error response:",
                error_body[:500]
            )

        return None

    except urllib.error.URLError as e:

        print(
            "DB Timetables Networkerror:",
            repr(e)
        )

        return None

    except TimeoutError:

        print(
            "DB Timetables Timeout:",
            url
        )

        return None

    except Exception as e:

        print(
            "DB Timetables Error:",
            repr(e)
        )

        return None

def get_db_station_eva(station_name):
    """
    Find the DB EVA number for a station.

    Search order:
        1. config.DB_STATION_EVA
        2. config.STATION_EVA_MAP
        3. runtime cache
        4. DB /station/{pattern}

    Returns:
        EVA number as string
        or None
    """

    if not station_name:
        return None

    clean_name = str(station_name).strip()

    if not clean_name:
        return None

    normalized_name = normalize(clean_name).upper()

    # ==================================================
    # 1. DIRECT CONFIG VALUE
    # ==================================================

    configured_eva = getattr(
        config,
        "DB_STATION_EVA",
        None
    )

    if configured_eva:

        eva = str(configured_eva).strip()

        if eva.isdigit():
            return eva

    # ==================================================
    # 2. STATION EVA MAP
    # ==================================================

    station_map = getattr(
        config,
        "STATION_EVA_MAP",
        None
    )

    if isinstance(station_map, dict):

        # Exact match
        if clean_name in station_map:

            eva = str(
                station_map[clean_name]
            ).strip()

            if eva.isdigit():
                return eva

        # Normalized match
        for key, value in station_map.items():

            if normalize(
                str(key)
            ).upper() == normalized_name:

                eva = str(value).strip()

                if eva.isdigit():
                    return eva

    # ==================================================
    # 3. RUNTIME CACHE
    # ==================================================

    cache_key = (
        "STATION_EVA",
        normalized_name
    )

    with db_cache_lock:

        cached = db_train_cache.get(
            cache_key
        )

        if cached:

            if cached.get("type") == "station":

                eva = str(
                    cached.get("eva", "")
                ).strip()

                if eva.isdigit():
                    return eva

    # ==================================================
    # 4. DB API
    # ==================================================

    encoded_name = urllib.parse.quote(
        clean_name,
        safe=""
    )

    data = db_api_get(
        f"/station/{encoded_name}"
    )

    if not data:

        print(
            f"No DB EVA number found for "
            f"'{clean_name}'."
        )

        return None

    try:

        root = ET.fromstring(data)

    except ET.ParseError as e:

        print(
            "DB Station XML could not "
            "be read:",
            repr(e)
        )

        return None

    # ==================================================
    # FIND EVA ATTRIBUTE
    # ==================================================

    candidates = []

    for element in root.iter():

        tag = (
            element.tag
            .split("}")[-1]
            .lower()
        )

        eva = element.get("eva")

        if eva:

            eva = str(eva).strip()

            if eva.isdigit():

                candidates.append(
                    (
                        tag,
                        eva,
                        (
                            element.text.strip()
                            if element.text
                            else ""
                        )
                    )
                )

    # Prefer station elements.
    for tag, eva, text in candidates:

        if tag in (
            "station",
            "stop",
            "stopplace"
        ):

            if (
                not text
                or normalized_name in normalize(text).upper()
                or normalize(text).upper() in normalized_name
            ):

                with db_cache_lock:

                    db_train_cache[cache_key] = {
                        "type": "station",
                        "eva": eva,
                        "timestamp": time.time()
                    }

                print(
                    f"DB Station found: "
                    f"{clean_name} -> EVA {eva}"
                )

                return eva

    # ==================================================
    # FALLBACK: ANY EVA ATTRIBUTE
    # ==================================================

    if candidates:

        eva = candidates[0][1]

        with db_cache_lock:

            db_train_cache[cache_key] = {
                "type": "station",
                "eva": eva,
                "timestamp": time.time()
            }

        print(
            f"DB Station found: "
            f"{clean_name} -> EVA {eva}"
        )

        return eva

    print(
        f"No DB EVA number found for "
        f"'{clean_name}'."
    )

    return None

def get_db_plan(eva_no, date, hour):
    """
    Download and cache one DB planned timetable hour.

    date:
        YYMMDD

    hour:
        HH
    """

    cache_key = (
        str(eva_no),
        date,
        int(hour)
    )

    with db_cache_lock:

        cached = db_plan_cache.get(cache_key)

        if cached:

            age = time.time() - cached["timestamp"]

            if age < config.DB_CACHE_TIME:
                return cached["data"]

    path = (
        f"/plan/"
        f"{eva_no}/"
        f"{date}/"
        f"{int(hour):02d}"
    )

    print(
        f"DB Timetable: Load {eva_no} "
        f"{date} {int(hour):02d}:00"
    )

    data = db_api_get(path)

    if not data:
        return None

    with db_cache_lock:

        db_plan_cache[cache_key] = {
            "timestamp": time.time(),
            "data": data
        }

    return data

def get_db_changes(eva_no):
    """
    Download and cache the DB full-change timetable.

    Endpoint:
        /fchg/{evaNo}

    The DB API documents /fchg/{evaNo} as the endpoint
    for current timetable changes.
    """

    if not eva_no:
        return None

    eva_no = str(eva_no).strip()

    cache_key = eva_no

    with db_cache_lock:

        cached = db_fchg_cache.get(
            cache_key
        )

        if cached:

            age = (
                time.time()
                - cached["timestamp"]
            )

            cache_time = getattr(
                config,
                "DB_FCHG_CACHE_TIME",
                30
            )

            if age < cache_time:

                debug_print(
                    f"DB FCHG cache HIT: {eva_no}"
                )

                return cached["data"]

    path = (
        f"/fchg/"
        f"{urllib.parse.quote(eva_no, safe='')}"
    )

    print(
        f"DB Timetable: Load changes "
        f"{eva_no}"
    )

    data = db_api_get(path)

    if not data:
        return None

    with db_cache_lock:

        db_fchg_cache[cache_key] = {
            "timestamp": time.time(),
            "data": data
        }

    return data

def parse_db_change_by_time(
    data,
    wanted_category,
    planned_departure,
    destination=None,
    time_tolerance_minutes=2
):
    """
    Find a train in the DB full-change (/fchg) feed.

    The fchg feed uses the same timetable-style <s>, <tl>,
    <ar> and <dp> structure as the planned timetable.

    Returns:
        "ICE 123"
        "IC 2024"
        "FLX 1234"
        or None
    """

    if not data:
        return None

    try:

        root = ET.fromstring(data)

    except ET.ParseError as e:

        print(
            "DB FCHG XML Error:",
            repr(e)
        )

        return None

    wanted_category = normalize(
        wanted_category
    ).upper()

    wanted_destination = normalize(
        destination or ""
    ).upper()

    best_match = None
    best_score = None

    # ==================================================
    # ITERATE THROUGH SERVICES
    # ==================================================

    for service in root.iter():

        tag = (
            service.tag
            .split("}")[-1]
            .lower()
        )

        if tag != "s":
            continue

        train_info = None
        departure = None
        arrival = None

        for child in service:

            child_tag = (
                child.tag
                .split("}")[-1]
                .lower()
            )

            if child_tag == "tl":
                train_info = child

            elif child_tag == "dp":
                departure = child

            elif child_tag == "ar":
                arrival = child

        if train_info is None:
            continue

        category = (
            train_info.get("c", "")
            .strip()
            .upper()
        )

        train_number = (
            train_info.get("n", "")
            .strip()
        )

        if not train_number:
            continue

        # ==================================================
        # CATEGORY
        # ==================================================

        if wanted_category == "DPF":

            if category not in (
                "DPF",
                "FLX",
                "IC",
                "ICE"
            ):
                continue

        else:

            if category != wanted_category:
                continue

        # ==================================================
        # TIME
        # ==================================================

        event = (
            departure
            if departure is not None
            else arrival
        )

        if event is None:
            continue

        actual_time = (
            event.get("ct", "").strip()
            or event.get("pt", "").strip()
        )

        if not actual_time:
            continue

        try:

            service_time = datetime.strptime(
                actual_time,
                "%y%m%d%H%M"
            )

        except ValueError:

            continue

        difference_seconds = abs(
            (
                service_time
                - planned_departure
            ).total_seconds()
        )

        if (
            difference_seconds
            > time_tolerance_minutes * 60
        ):
            continue

        # ==================================================
        # DESTINATION
        # ==================================================

        destination_match = False

        if wanted_destination:

            destination_values = []

            # Look at all textual information in this
            # timetable service.
            for child in service.iter():

                text = (
                    child.text.strip()
                    if child.text
                    else ""
                )

                if not text:
                    continue

                child_tag = (
                    child.tag
                    .split("}")[-1]
                    .lower()
                )

                if child_tag in (
                    "n",
                    "name",
                    "destination",
                    "dp",
                    "ar",
                    "station"
                ):

                    destination_values.append(
                        normalize(text).upper()
                    )

            destination_text = " ".join(
                destination_values
            )

            if wanted_destination in destination_text:

                destination_match = True

            else:

                words = [
                    word
                    for word in wanted_destination.split()
                    if len(word) >= 4
                ]

                if words and all(
                    word in destination_text
                    for word in words
                ):

                    destination_match = True

        # ==================================================
        # SCORE
        # ==================================================

        score = (
            0 if destination_match else 1,
            difference_seconds
        )

        if (
            best_score is None
            or score < best_score
        ):

            best_score = score

            best_match = (
                f"{category} "
                f"{train_number}"
            )

    return best_match

def parse_db_train(data, wanted_category, wanted_train_number):

    if not data:
        return None

    try:
        root = ET.fromstring(data)

    except Exception as e:

        print(
            "DB Timetable XML Error:",
            repr(e)
        )

        return None

    wanted_number = str(wanted_train_number)

    candidates = []

    for element in root.iter():

        text = (
            element.text.strip()
            if element.text
            else ""
        )

        if not text:
            continue

        normalized = normalize(text)

        if (
            normalized == normalize(
                f"{wanted_category} {wanted_number}"
            )
            or normalized == normalize(
                f"{wanted_category}{wanted_number}"
            )
            or normalized == wanted_number
        ):
            candidates.append(element)

    if not candidates:
        return None

    result = {
        "category": wanted_category,
        "number": wanted_number,
        "name": f"{wanted_category} {wanted_number}",
        "destination": "",
        "origin": "",
        "platform": "",
        "departure": ""
    }

    # Inspect the surrounding timetable entry.
    for match in candidates:

        parent = None

        for possible_parent in root.iter():

            for child in possible_parent:

                if child is match:
                    parent = possible_parent
                    break

            if parent is not None:
                break

        if parent is None:
            continue

        for child in parent.iter():

            tag = child.tag.lower()

            text = (
                child.text.strip()
                if child.text
                else ""
            )

            if not text:
                continue

            # Train number/name
            if (
                tag.endswith("tl")
                or tag.endswith("n")
            ):

                if (
                    normalize(wanted_category) in normalize(text)
                    or text == wanted_number
                ):
                    result["name"] = text

            # Destination
            elif tag.endswith("dp"):

                result["destination"] = text

            # Origin
            elif tag.endswith("ar"):

                result["origin"] = text

            # Platform
            elif tag.endswith("track"):

                result["platform"] = text

        break

    return result

def lookup_db_train(
    category,
    train_number,
    station_name,
    target_time=None
):
    """
    Legacy-compatible DB train lookup.

    This function is kept because older parts of TransitMatrix
    may still call it.

    It delegates to lookup_db_train_by_time().
    """

    if target_time is None:
        target_time = datetime.now()

    category = normalize(category).upper()
    train_number = str(train_number).strip()

    if not train_number:
        return None

    # Use configured EVA if available.
    # station_name is retained for backwards compatibility.
    old_station_name = config.STATION_NAME

    try:

        if station_name:
            config_station_name = station_name
        else:
            config_station_name = old_station_name

        # We do NOT modify config.
        # We only use it as the fallback station.

        destination = ""

        cache_key = (
            "LEGACY",
            category,
            train_number,
            normalize(config_station_name),
            target_time.strftime(
                "%y%m%d%H%M"
            )
        )

        with db_cache_lock:

            cached = db_train_cache.get(
                cache_key
            )

            if cached:

                age = (
                    time.time()
                    - cached["timestamp"]
                )

                if age < config.DB_CACHE_TIME:

                    return cached.get("data")

        eva = getattr(
            config,
            "DB_STATION_EVA",
            None
        )

        if not eva:

            eva = get_db_station_eva(
                config_station_name
            )

        if not eva:

            return None

        eva = str(eva).strip()

        result = None

        hours_to_check = [
            target_time - timedelta(hours=1),
            target_time,
            target_time + timedelta(hours=1)
        ]

        checked = set()

        for check_time in hours_to_check:

            key = (
                check_time.strftime("%y%m%d"),
                check_time.hour
            )

            if key in checked:
                continue

            checked.add(key)

            data = get_db_plan(
                eva,
                key[0],
                key[1]
            )

            if not data:
                continue

            result = parse_db_train_by_time(
                data,
                category,
                train_number,
                target_time
            )

            if result:
                break

        if result is None:

            change_data = get_db_changes(eva)

            if change_data:

                result = parse_db_change_by_time(
                    change_data,
                    category,
                    target_time
                )

                # Don't accept another train.
                if result:

                    parts = result.split(
                        " ",
                        1
                    )

                    if (
                        len(parts) != 2
                        or parts[1] != train_number
                    ):

                        result = None

        with db_cache_lock:

            db_train_cache[cache_key] = {
                "timestamp": time.time(),
                "data": result
            }

        if result:

            print(
                f"DB Train found: {result}"
            )

        else:

            print(
                f"DB Train not found: "
                f"{category} {train_number}"
            )

        return result

    except Exception as e:

        print(
            "Legacy DB lookup Error:",
            repr(e)
        )

        return None

def get_announcements(departures=None):

    update_announcement_line_cache(departures)

    with announcement_line_cache_lock:
        announcement_lines = set(
            announcement_line_cache.keys()
        )

    print(
        "Monitoring announcement lines:",
        ", ".join(sorted(announcement_lines))
    )

    url = (
        config.HVV_API_URL.rstrip("/")
        + "/gti/public/getAnnouncements"
    )

    payload = {
        "language": "de",
        "version": 63,
        "names": sorted(announcement_lines),
        "full": True,
        "showBroadcastRelevant": True,
    }

    body = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False
    )

    headers = {
        "geofox-auth-user": credentials.HVV_API_USER,
        "geofox-auth-signature": get_signature(body),
        "geofox-auth-type": "HmacSHA1",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "TransitMatrix"
    }

    request = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            raw = response.read()

            return json.loads(
                raw.decode(
                    "utf-8",
                    errors="replace"
                )
            )

    except urllib.error.HTTPError as e:

        print(
            f"Announcements HTTP Error {e.code}."
        )

        if e.code in (429, 503):

            if e.code == 429:
                detail_text = "TOO MANY REQUESTS"
            else:
                detail_text = "SERVICE UNAVAILABLE"

            return {
                "announcements": [
                    {
                        "id": f"HTTP_{e.code}",
                        "description": (
                            f"HTTP ERROR {e.code} - "
                            f"{detail_text}"
                        ),
                        "locations": []
                    }
                ]
            }

        raise

    except urllib.error.URLError as e:

        print(
            "Announcements Networkerror",
            repr(e)
        )

        raise

    except json.JSONDecodeError as e:

        print(
            "Announcements JSON Error:",
            repr(e)
        )

        raise


def parse_announcements(data):

    result = []

    for announcement in data.get("announcements", []):

        text = announcement.get(
            "description",
            ""
        ).strip()

        locations = []
        seen_locations = set()

        for loc in announcement.get("locations", []):

            line = loc.get("line")

            if not line:
                continue

            location = {
                "line": normalize(line.get("name", "")),
                "direction": normalize(line.get("direction", "")),
                "origin": normalize(line.get("origin", "")),
                "begin": normalize(
                    loc.get("begin", {}).get("name", "")
                    if isinstance(loc.get("begin"), dict)
                    else ""
                ),
                "end": normalize(
                    loc.get("end", {}).get("name", "")
                    if isinstance(loc.get("end"), dict)
                    else ""
                ),
                "bothDirections": loc.get(
                    "bothDirections",
                    True
                )
            }

            # A line/direction combination only needs to occur once.
            location_key = (
                location["line"],
                location["direction"],
                location["bothDirections"]
            )

            if location_key in seen_locations:
                continue

            seen_locations.add(location_key)
            locations.append(location)

        result.append({
            "id": announcement.get("id", ""),
            "lines": locations,
            "text": text,
            "color": "red"
        })

    return result


def has_line_announcement(bus):
    if not line_announcements:
        return False

    bus_line = normalize(bus.get("linie", ""))
    bus_direction = normalize(bus.get("ziel", ""))

    if not bus_line:
        return False

    for announcement in line_announcements:
        for location in announcement.get("lines", []):
            # Check if it's a dictionary (API format) or a string (simple test format)
            if isinstance(location, dict):
                announcement_line = normalize(location.get("line", ""))
                both_directions = location.get("bothDirections", True)
                announcement_direction = normalize(location.get("direction", ""))
            else:
                announcement_line = normalize(str(location))
                both_directions = True
                announcement_direction = ""

            if announcement_line != bus_line:
                continue

            if both_directions:
                return True

            if announcement_direction:
                if announcement_direction == bus_direction:
                    return True
                if announcement_direction in bus_direction or bus_direction in announcement_direction:
                    return True

            if not announcement_direction:
                return True

    return False

def update_announcement_line_cache(departures):
    now = time.time()

    configured_lines = {
        normalize(str(line).strip())
        for line in config.MONITORED_LINES
        if str(line).strip()
    }

    with announcement_line_cache_lock:

        # Always keep configured lines
        for line in configured_lines:
            announcement_line_cache[line] = now

        # Add or refresh lines currently appearing
        # in the departure list.
        for departure in departures or []:
            line = departure.get("linie")

            if line:
                line = normalize(str(line).strip())

                if line:
                    announcement_line_cache[line] = now

        # Remove automatically discovered lines
        # after the configured cache lifetime.
        expired = [
            line
            for line, timestamp
            in announcement_line_cache.items()
            if (
                line not in configured_lines
                and now - timestamp > config.ANNOUNCEMENT_LINE_CACHE_TIME
            )
        ]

        for line in expired:
            del announcement_line_cache[line]

def draw_no_departures(matrix):
    global no_departures_blink
    global data_status

    if not no_departures_blink:
        return

    # Check if any bus data target contains NO STATION
    if data_status == "NO_STATION" or (bus_data and bus_data[0].get("ziel") == "NO STATION"):
        lines = [
            "STATION",
            "NICHT",
            "DEFINIERT",
            "",
            "CONFIG",
            "PRÜFEN"
        ]
    elif data_status == "OFFLINE":
        lines = [
            "KEINE",
            "VERBINDUNG"
        ]
    else:
        lines = [
            "KEINE",
            "ABFAHRTEN",
            "GEPLANT"
        ]

    total_height = len(lines) * config.CHAR_HEIGHT + (len(lines) - 1) * 4
    start_y = (config.HEIGHT - total_height) // 2

    for i, text in enumerate(lines):
        width = len(text) * config.CHAR_WIDTH
        x = (config.WIDTH - width) // 2
        y = start_y + i * (config.CHAR_HEIGHT + 4)
        draw_text(matrix, x, y, text)

def get_message_text():

    global current_message

    if not messages:
        return ""

    if current_message >= len(messages):
        current_message = 0

    msg = messages[current_message]

    lines = msg.get("lines", [])
    text = msg.get("text", "")

    if lines:
        line_names = get_unique_announcement_lines(msg)

        if line_names:
            prefix = "!" + ",".join(line_names) + "!: "
        else:
            prefix = "!MELDUNG!:"
    else:
        prefix = "!MELDUNG!:"

    return prefix + text + " +++ "

def draw_message(matrix):
    global current_message

    if not messages:
        return

    if current_message >= len(messages):
        current_message = 0

    msg = messages[current_message]
    lines = msg.get("lines", [])

    if lines:
        line_names = get_unique_announcement_lines(msg)

        if line_names:
            header = "!" + ",".join(line_names) + ":"
        else:
            header = "!MELDUNG!:"
    else:
        header = "!MELDUNG!:"
    # ==========================================
    # Counter Logic (z.B. "1/2")
    # ==========================================
    total_msgs = len(messages)
    show_counter = False
    counter_text = ""
    counter_width = 0

    if total_msgs > 1:
        # Display the counter for 2 seconds, then hide it for 3 seconds.
        if int(time.time()) % 5 >= 3:
            show_counter = True
            counter_text = f"{current_message + 1}/{total_msgs}"
            counter_width = get_text_width(counter_text)

    # Calculate how much space remains for the header.
    available_pixels = config.WIDTH
    if show_counter:
        available_pixels -= (counter_width + 2) # Deduct space for the meter + some clearance.

    max_header_chars = available_pixels // config.CHAR_WIDTH

    # ==========================================
    # DRAW HEADER (LINES)
    # ==========================================
    if get_text_width(header) > available_pixels:
        header_display = get_scroll_text(
            header,
            message_scroll_offset,
            max_header_chars
        )
    else:
        header_display = header

    # Header in red (ColorCode.DELAY)
    draw_text(matrix, 0, 48, header_display, config.ColorCode.DELAY)

    # Show Counter
    if show_counter:
        counter_x = config.WIDTH - counter_width
        draw_text(matrix, counter_x, 48, counter_text, config.ColorCode.DEFAULT)

    # ==========================================
    # SCROLL MESSAGE TEXT
    # ==========================================
    text = normalize(msg.get("text", "")) + " +++ "
    text_scroll = get_scroll_text(
        text,
        message_scroll_offset,
        10
    )
    draw_text(matrix, 0, 56, text_scroll, config.ColorCode.DELAY)

# DISPLAY

def draw_reload_bar(matrix):
    global reload_progress
    global data_status

    # Clear bottom row
    for x in range(config.WIDTH):
        set_pixel(matrix, x, config.HEIGHT - 1, 0)

    # Set red for any error status, green for normal operation
    if data_status != "OK":
        bar_color = config.ColorCode.DELAY
    else:
        bar_color = config.ColorCode.OK

    # Draw progress bar
    for x in range(reload_progress):
        set_pixel(matrix, x, config.HEIGHT - 1, bar_color)

def update_display():
    matrix = create_matrix()
    global reload_progress
    global last_update_time
    global reload_start_time

    if show_station_header and station_names:
        draw_text(
            matrix,
            0,
            0,
            normalize(station_names[0])
        )

    # Check if the first bus entry contains an error/no data flag
    if bus_data and bus_data[0].get("nodata"):
        draw_no_departures(matrix)
    else:
        max_departures = 3 if show_station_header else 4

        if messages:
            max_departures = 3

        for i, bus in enumerate(bus_data[:max_departures]):
            draw_bus_block(
                matrix,
                i,
                bus
            )

        if messages:
            draw_message(matrix)

    draw_reload_bar(matrix)
    show_matrix(matrix)

def update_data():
    global bus_data
    global data_status
    global station_names
    global show_station_header
    global reload_start_time
    global reload_progress
    global needs_render
    global next_reload_pixel_time

    while True:
        print("Loading departures...")
        data = []

        # Replace the try/except inside update_data() with this:
        try:
            if config.DATA_SOURCE == "HVV":
                data = get_hvv_data()

                # Check if the returned data indicates an error state
                if data and data[0].get("nodata"):
                    if data[0].get("ziel") == "NO STATION":
                        data_status = "NO_STATION"
                    else:
                        data_status = "OFFLINE"
                else:
                    data_status = "OK"

        except Exception as e:
            print("ERROR LOADING DATA:", repr(e))
            data_status = "OFFLINE"
            data = []

        station_names = []

        for bus in data:
            name = bus.get("station", {}).get("name", "")
            if name and name not in station_names:
                station_names.append(name)

        show_station_header = len(station_names) > 1

        data = remove_duplicates(data)

        if data:
            bus_data = data
            reload_start_time = time.time()
            reload_progress = config.WIDTH
            next_reload_pixel_time = reload_start_time + (config.DATA_UPDATE / config.WIDTH)
            needs_render = True
            print_terminal(data)

        else:

            reload_start_time = time.time()
            reload_progress = config.WIDTH
            next_reload_pixel_time = reload_start_time + (config.DATA_UPDATE / config.WIDTH)

            bus_data = [

                {

                    "linie": "",

                    "ziel": "KEINE",

                    "plan": "",

                    "zeit": "",

                    "nodata": True

                },

                {

                    "linie": "",

                    "ziel": "ABFAHRTEN",

                    "plan": "",

                    "zeit": "",

                    "nodata": True

                },

                {

                    "linie": "",

                    "ziel": "GEPLANT",

                    "plan": "",

                    "zeit": "",

                    "nodata": True

                }

            ]

        time.sleep(
            config.DATA_UPDATE
        )
def update_messages(departures):
    global messages
    global line_announcements

    try:
        data = get_announcements(departures)

        parsed = parse_announcements(data)

        # All updates for the announcement ticker
        messages = parsed

        # Regardless of the ! at the departures
        line_announcements = parsed

        print(
            "Announcement loaded:",
            len(messages)
        )

        for announcement in line_announcements:
            print(
                "  Announcement:",
                announcement.get("text", "")[:100]
            )

            for location in announcement.get("lines", []):
                print(
                    "    Line:",
                    location.get("line"),
                    "| Direction:",
                    location.get("direction"),
                    "| Both:",
                    location.get("bothDirections")
                )

    except Exception as e:

        print(
            "Announcements could not be loaded:",
            e
        )

        messages = []
        line_announcements = []

def get_unique_announcement_lines(announcement):
    """Return each affected line only once for the announcement ticker."""

    unique_lines = []
    seen = set()

    for location in announcement.get("lines", []):
        line = normalize(location.get("line", ""))

        if not line:
            continue

        if line in seen:
            continue

        seen.add(line)
        unique_lines.append(line)

    return unique_lines

def update_messages_loop():
    while True:
        # Pass the global bus_data directly!
        update_messages(bus_data)
        time.sleep(60)

# CENTRAL ANIMATION & RENDERING CLOCK

def ensure_scroll_arrays():

    while len(scroll_offset) < len(bus_data):
        scroll_offset.append(0)

    while len(scroll_wait) < len(bus_data):
        scroll_wait.append(0)

    while len(time_scroll_offset) < len(bus_data):
        time_scroll_offset.append(0)

    while len(line_scroll_offset) < len(bus_data):
        line_scroll_offset.append(0)

def update_brightness():

    global matrix_led
    global current_brightness

    if matrix_led is None:
        return

    hour = datetime.now().hour

    if hour >= config.NIGHT_START or hour < config.NIGHT_END:
        brightness = config.NIGHT_BRIGHTNESS
    else:
        brightness = config.DAY_BRIGHTNESS

    if current_brightness != brightness:

        matrix_led.brightness = brightness

        current_brightness = brightness

        print(
            f"Brightness set to {brightness}%"
        )


def init_led():

    global matrix_led
    global led_canvas
    global current_brightness

    if RGBMatrixOptions is None:
        print("ERROR: rgbmatrix library missing.")
        exit(1)

    if os.geteuid() != 0:
        print("ERROR: Run LED mode with sudo.")
        exit(1)

    options = RGBMatrixOptions()

    options.rows = 64
    options.cols = 64
    options.chain_length = 1
    options.parallel = 1

    options.hardware_mapping = "regular"
    options.gpio_slowdown = 3

    matrix_led = RGBMatrix(options=options)

    current_brightness = None

    update_brightness()

    led_canvas = matrix_led.CreateFrameCanvas()

def show_led(matrix):

    global matrix_led
    global led_canvas

    if matrix_led is None or led_canvas is None:
        return

    frame = led_canvas

    rgb = {
        config.ColorCode.DEFAULT: hex_to_rgb(config.HEX_COLORS[config.ColorCode.DEFAULT]),
        config.ColorCode.DELAY: hex_to_rgb(config.HEX_COLORS[config.ColorCode.DELAY]),
        config.ColorCode.OK: hex_to_rgb(config.HEX_COLORS[config.ColorCode.OK]),
        config.ColorCode.SBAHN: hex_to_rgb(config.HEX_COLORS[config.ColorCode.SBAHN]),
        config.ColorCode.UBAHN: hex_to_rgb(config.HEX_COLORS[config.ColorCode.UBAHN]),
        config.ColorCode.AKN: hex_to_rgb(config.HEX_COLORS[config.ColorCode.AKN]),
        config.ColorCode.WHITE: hex_to_rgb(config.HEX_COLORS[config.ColorCode.WHITE]),
        config.ColorCode.SEV: hex_to_rgb(config.HEX_COLORS[config.ColorCode.SEV]),
        config.ColorCode.REGIO: hex_to_rgb(config.HEX_COLORS[config.ColorCode.REGIO]),
        config.ColorCode.MESSAGE: hex_to_rgb(config.HEX_COLORS[config.ColorCode.MESSAGE]),
        config.ColorCode.FLX: hex_to_rgb(config.HEX_COLORS[config.ColorCode.FLX]),
    }

    for y in range(config.HEIGHT):

        for x in range(config.WIDTH):

            value = matrix[y][x]

            if value in rgb:
                r, g, b = rgb[value]
            else:
                r, g, b = 0, 0, 0

            frame.SetPixel(
                x,
                y,
                r,
                g,
                b
            )

    led_canvas = matrix_led.SwapOnVSync(frame)
def check_delays():

    limit = 3 if show_station_header else 4

    for bus in bus_data[:limit]:

        if not bus.get("delay_found", False):
            continue

        zeit = normalize(
            bus.get("zeit", "")
        ).lower()

        # Ignore delay if already NOW
        if (
            "sofort" in zeit
            or "jetzt" in zeit
            or "now" in zeit
        ):
            continue

        return True

    return False

def master_render_loop():
    global blink_state
    global time_display_mode
    global no_departures_blink
    global message_scroll_offset
    global current_message
    global last_reload_time
    global reload_progress
    global needs_render
    global next_reload_pixel_time

    if needs_render:
        needs_render = False

    last_scroll_time = 0
    last_message_scroll_time = 0
    last_blink_time = 0
    last_mode_time = 0
    last_no_departures_blink = 0

    scroll_interval = 0.4
    message_scroll_interval = 0.25
    blink_interval = 0.5
    no_data_blink_interval = 1.0
    mode_interval = 2.0

    while True:
        current_time = time.time()
        update_brightness()
        needs_redraw = False

        # RELOAD-BAR
        if current_time >= next_reload_pixel_time:
            reload_progress -= 1
            if reload_progress < 0:
                reload_progress = 0
            next_reload_pixel_time += config.DATA_UPDATE / config.WIDTH
            needs_redraw = True

        # SCROLL DEPARTURES & LINES
        if current_time - last_scroll_time >= scroll_interval:
            last_scroll_time = current_time
            needs_redraw = True

            if bus_data:
                ensure_scroll_arrays()

                max_departures = 3 if show_station_header else 4

                # Limit animated departures when messages exist
                if messages:
                    max_departures = 3

                # Determine space for line display
                line_pixel_space = config.WIDTH - (5 * config.CHAR_WIDTH)

                for i, bus in enumerate(bus_data[:max_departures]):
                    # Line scrolling
                    line = normalize(bus.get("linie", ""))
                    if get_text_width(line) > line_pixel_space:
                        line_scroll_offset[i] += 1
                        if line_scroll_offset[i] >= len(line + "   "):
                            line_scroll_offset[i] = 0

                    # Destination Scrolling
                    if scroll_wait[i] > 0:
                        scroll_wait[i] -= 1
                    else:
                        ziel = normalize(bus.get("ziel", ""))
                        if len(ziel) >= config.WIDTH // config.CHAR_WIDTH:
                            scroll_offset[i] += 1
                            if scroll_offset[i] >= len(ziel + "   "):
                                scroll_offset[i] = 0
                                scroll_wait[i] = 8
                        else:
                            scroll_offset[i] = 0

        # SCROLL FOR INFORMATION MESSAGE
        if current_time - last_message_scroll_time >= message_scroll_interval:
            last_message_scroll_time = current_time

            if len(messages) > 0:
                if current_message >= len(messages):
                    current_message = 0

                msg = messages[current_message]
                message_scroll_offset += 1

                full_scroll_text = normalize(msg.get("text", "")) + " +++ "

                if message_scroll_offset >= len(full_scroll_text) * 2:
                    message_scroll_offset = 0
                    current_message += 1

                    if current_message >= len(messages):
                        current_message = 0

                needs_redraw = True

        # NORMAL FLASHING
        if current_time - last_blink_time >= blink_interval:
            last_blink_time = current_time
            blink_state = not blink_state
            needs_redraw = True

        # FLASHING INDICATE NO TRAIN DEPARTURES
        if bus_data and bus_data[0].get("nodata"):
            if current_time - last_no_departures_blink >= no_data_blink_interval:
                last_no_departures_blink = current_time
                no_departures_blink = not no_departures_blink
                needs_redraw = True

        # TIME / MINUTE CHANGE
        if current_time - last_mode_time >= mode_interval:
            last_mode_time = current_time

            if check_delays():
                time_display_mode = (time_display_mode + 1) % 3
            else:
                time_display_mode = 2 if time_display_mode == 0 else 0

            needs_redraw = True

        # RENDER
        if needs_redraw:
            try:
                if config.DISPLAY_MODE == "WINDOW":
                    window.after(0, update_display)
                else:
                    update_display()
            except Exception as e:
                print("Render Error:", repr(e))
                time.sleep(1)
                continue

        time.sleep(0.05)

# NORMALIZE TEXT

def normalize(text):

    replacements = {
        "ç": "Ç",
        "ó": "Ó",
        "Ó": "Ó",
        "é": "É",
        "É": "É",
        "è": "È",
        "È": "È",

        "ä": "Ä",
        "ö": "Ö",
        "ü": "Ü",
        "ß": "SS",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return (
        text
        .replace("_", " ")
        .replace("#ddb", "")
        .upper()
    )

if __name__ == "__main__":

    # CLEAN OLD DB FILES BEFORE START

    cleanup_db_timetable_files()

    # CLEAN ON NORMAL PYTHON EXIT

    atexit.register(
        cleanup_db_timetable_files
    )

    try:

        # ==================================================
        # DISPLAY INITIALIZATION
        # ==================================================

        if config.DISPLAY_MODE == "LED":

            init_led()

        elif config.DISPLAY_MODE == "WINDOW":

            create_window()

        else:

            raise ValueError(
                f"Invalid DISPLAY_MODE: "
                f"{config.DISPLAY_MODE}"
            )

        # ==================================================
        # DATA THREAD
        # ==================================================

        threading.Thread(
            target=update_data,
            name="TransitMatrix-Data",
            daemon=True
        ).start()

        # ==================================================
        # ANNOUNCEMENT THREAD
        # ==================================================

        if config.DATA_SOURCE == "HVV":

            threading.Thread(
                target=update_messages_loop,
                name="TransitMatrix-Messages",
                daemon=True
            ).start()

        # ==================================================
        # RENDER THREAD
        # ==================================================

        threading.Thread(
            target=master_render_loop,
            name="TransitMatrix-Render",
            daemon=True
        ).start()

        # ==================================================
        # MAIN LOOP
        # ==================================================

        if (
            config.DISPLAY_MODE == "WINDOW"
            and window is not None
        ):

            window.mainloop()

        elif config.DISPLAY_MODE == "LED":

            while True:

                time.sleep(1)

    except KeyboardInterrupt:

        print(
            "\nProgram stopped by user."
        )

    except Exception as e:

        print(
            "\nFatal error:",
            repr(e)
        )

    finally:

        print(
            "Cleaning up DB timetable files..."
        )

        cleanup_db_timetable_files()

        print(
            "DB Timetable temporary files cleaned up."
        )