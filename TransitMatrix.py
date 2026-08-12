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
import tkinter as tk
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from ctypes import wintypes
from datetime import datetime, timedelta
from hashlib import sha1

import requests
from bs4 import BeautifulSoup

import config
from font import FONT
import credentials

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
# FARBEN
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

    # --- LINUX-FIX FÜR DAS ICON ---
    # 1. Ermittle den absoluten Ordnerpfad deines Skripts
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 2. Pfad zur Icon-Datei sauber zusammensetzen
    icon_path = os.path.join(script_dir, "icon.ico")

    try:
        # Falls du die Datei in icon.png umbenannt hast, hier "icon.png" eintragen
        icon_img = tk.PhotoImage(file=icon_path)
        window.tk.call("wm", "iconphoto", window._w, icon_img)
    except Exception as e:
        # Falls es unter Windows weiterhin mit .ico laufen soll, falls PNG fehlschlägt:
        try:
            window.iconbitmap(icon_path)
        except Exception:
            print(f"Icon konnte nicht geladen werden: {e}")
    # ------------------------------

    window.title("TransitMatrix")
    window.after(2000, cycle_window_title)

    # Feste Skalierung für Tkinter
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

    window.geometry(
        f"{config.WIDTH * config.SCALE}x" f"{config.HEIGHT * config.SCALE}"
    )

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
# TERMINAL AUSGABE

def print_terminal(data):

    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)

    print("="*80)

    print(
        f"{'LINIE':<8}"
        f"{'ZIEL':<30}"
        f"{'PLAN':<10}"
        f"{'ZEIT':<12}"
        f"{'DELAY':<8}"
    )

    print("="*80)

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

    print("="*80)

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

# EINZELNES ZEICHEN

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
# SCROLL

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

    # --- Linienanzeige berechnen ---
    if get_text_width(line) > line_pixel_space:
        line_display = get_scroll_text(
            line,
            line_scroll_offset[index],
            max_line_chars
        )
    else:
        line_display = line

    line_color = get_line_color(line)

    # --- Daten aus bus lesen ---
    ziel = normalize(bus.get("ziel", ""))
    plan = bus.get("plan", "")
    zeit_raw = bus.get("zeit", "")
    delay = bus.get("delay", 0)
    delay_found = bus.get("delay_found", False)

    # --- Planzeit bereinigen (für Breiten/Collision) ---
    plan_time_clean = re.sub(r"\s*\+\s*\d+", "", plan).strip()

    # Muss die Linie überhaupt scrollen?
    line_scrolls = get_text_width(line) > line_pixel_space

    # Nur bei scrollenden Linien besteht Kollisionsgefahr
    if line_scrolls:
        full_line_width = get_text_width(line)
        time_x = config.WIDTH - get_text_width(plan_time_clean)
        touches_time = full_line_width >= time_x
    else:
        touches_time = False

    # --- Linienanzeige zeichnen ---
    # Nur echte S-/U-/A-Linien bekommen Buchstaben
    # "SEV" darf NICHT als S-Bahn erkannt werden.
    is_logo_line = re.match(
        r"^(S|U|A)(?:\d+)?$",
        line.strip(),
        re.IGNORECASE
    )

    if is_logo_line:
        draw_text(
            matrix,
            0,
            y_line,
            line_display[0],
            line_color
        )

        draw_text(
            matrix,
            config.CHAR_WIDTH,
            y_line,
            line_display[1:],
            config.ColorCode.DEFAULT
        )

    else:
        draw_text(
            matrix,
            0,
            y_line,
            line_display,
            line_color
        )

    # =====================
    # MINUTEN & "NOW" LOGIK
    # =====================

    display_minutes = ""
    zeit_lower = normalize(zeit_raw).lower()

    # 1. Prüfen, ob die API explizit Ausfall oder NOW meldet
    is_cancelled = "fällt aus" in zeit_lower
    api_now = (
            "sofort" in zeit_lower
            or "sofor" in zeit_lower
            or "jetzt" in zeit_lower
            or "now" in zeit_lower
            or re.search(r"\bin\s*0\s*min\b", zeit_lower) is not None
    )

    now_active = api_now

    # 2. Lokalen Countdown prüfen (falls API nicht ohnehin schon NOW sagt)
    target_time = bus.get("target_time")

    if not is_cancelled and not api_now and target_time:
        # Wie viele Sekunden sind es von JETZT bis zur Zielzeit?
        diff_seconds = (target_time - datetime.now()).total_seconds()

        # Auf die nächste volle Minute aufrunden
        minutes = math.ceil(diff_seconds / 60)

        if minutes <= 0:
            now_active = True
        elif minutes == 1:
            display_minutes = "1'"
        else:
            display_minutes = str(minutes) + "'"

    # Fallback, falls keine target_time da ist (z.B. beim ersten Start oder Fehler)
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
    # ZEIT RECHTS
    # =====================

    plan_time = plan_time_clean

    if now_active:
        now_text = "NOW" if blink_state else "   "
        time_x = config.WIDTH - get_text_width(now_text) + 1
        draw_text(matrix, time_x, y_line, now_text, config.ColorCode.DEFAULT)

    elif display_minutes == "AUS":
        cancel_text = "FÄLLT" if blink_state else "AUS"
        time_x = config.WIDTH - get_text_width(cancel_text) + 1
        draw_text(matrix, time_x, y_line, cancel_text, config.ColorCode.DELAY)

    elif time_display_mode == 0:

        time_x = config.WIDTH - get_text_width(plan_time)

        # Uhrzeit immer gelb
        time_color = config.ColorCode.DEFAULT

        draw_text(
            matrix,
            time_x,
            y_line,
            plan_time,
            time_color
        )

    else:

        if time_display_mode == 1 and delay_found:
            right_text = "+" + str(delay) + "'"

            if delay > 0:
                color = config.ColorCode.DELAY
            else:
                color = config.ColorCode.OK

        else:
            right_text = display_minutes
            color = config.ColorCode.DEFAULT

        time_width = get_text_width(right_text)

        # rechtsbündig an der letzten Pixelspalte
        time_x = config.WIDTH - time_width

        # nicht über die Linienanzeige laufen
        if time_x < 30:
            time_x = 30

        draw_text(
            matrix,
            time_x,
            y_line,
            right_text,
            color
        )

    # =====================
    # ZIEL UNTEN
    # =====================

    show_ring = ziel in ("RING S41", "RING S42")

    max_chars = 8 if show_ring else 10

    has_announcement = has_line_announcement(bus)

    target_display = get_scroll_text(
        ziel,
        scroll_offset[index],
        max_chars
    )

    draw_text(
        matrix,
        0,
        y_target,
        target_display,
        config.ColorCode.DEFAULT
    )

    # Rotes ! ganz rechts am Rand
    if has_announcement:
        exclamation = "!"

        exclamation_x = config.WIDTH - get_text_width(exclamation)

        draw_text(
            matrix,
            exclamation_x,
            y_target,
            exclamation,
            config.ColorCode.DELAY
        )

    if show_ring:
        symbol_x = get_text_width(target_display) + 2

        s41_bitmap = [
            "0011100",
            "0100010",
            "1000111",
            "1000010",
            "1000000",
            "0100010",
            "0011100",
        ]

        s42_bitmap = [
            "0011100",
            "0100010",
            "1110001",
            "0100001",
            "0000001",
            "0100010",
            "0011100",
        ]

        if ziel == "RING S41":
            bitmap = s41_bitmap
        elif ziel == "RING S42":
            bitmap = s42_bitmap
        else:
            bitmap = None

        if bitmap:
            for yy, row in enumerate(bitmap):
                for xx, pixel in enumerate(row):
                    if pixel == "1":
                        px = symbol_x + xx
                        py = y_target + yy

                        if 0 <= px < config.WIDTH and 0 <= py < config.HEIGHT:
                            set_pixel(
                                matrix,
                                px,
                                py,
                                config.ColorCode.DEFAULT
                            )

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

    # Linien wie E/525, H/123, X/45
    if re.fullmatch(
            r"[A-ZÄÖÜ]+/\d+",
            text
    ):
        return True


    # normale Linien
    if re.fullmatch(
                r"(MEX|ALX|FLX|FEX|ICE|ECE|IRE|ZUG|AST|KAT|SCH|SEV|RNV|AT|CB|RS|RE|RB|RJ|NJ|EN|GI|IC|IR|LM|EC|EV|FM|SB|TB|HS|S|U|A|C|X|M|N|R|F)(?:[\s-]*([A-Z]*\d+))?",
            text
    ):
        return True

    # normale Buslinien (z.B. 782, 501, 12)
    if re.fullmatch(
            r"[A-ZÄÖÜ]*\d+[A-ZÄÖÜ]*",
            text
    ):
        return True

    return False

def parse_db_train_by_time(
    data,
    category,
    planned_departure,
    time_tolerance_minutes=1
):
    """
    Find a DB train by category and departure time.

    Returns:
        "ICE 1234"
        "IC 1234"
        "DPF 1234"

    or None if no matching train was found.
    """

    if not data:
        return None

    try:

        root = ET.fromstring(data)

    except Exception as e:

        print(
            "DB Timetable XML Fehler:",
            repr(e)
        )

        return None

    wanted_category = normalize(
        category
    ).upper()

    best_match = None
    best_difference = None

    for element in root.iter():

        tag = (
            element.tag
            .split("}")[-1]
            .lower()
        )

        if tag != "s":
            continue

        tl = None
        dp = None
        ar = None

        for child in element:

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

        if train_category != wanted_category:
            continue

        # Prefer departure information.
        event = dp if dp is not None else ar

        if event is None:
            continue

        # Prefer changed time if present.
        # Otherwise use planned time.
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

        difference = abs(
            (
                db_departure -
                planned_departure
            ).total_seconds()
        )

        difference_minutes = (
            difference / 60
        )

        if (
            difference_minutes
            > time_tolerance_minutes
        ):
            continue

        if (
            best_difference is None
            or difference < best_difference
        ):

            best_difference = difference

            best_match = (
                f"{train_category} "
                f"{train_number}"
            )

    return best_match

def parse_db_change_by_time(
    data,
    category,
    planned_departure,
    time_tolerance_minutes=3
):
    """
    Find a train in the DB full-change feed by
    category and departure time.

    Returns:
        "ICE 1234"

    or None.
    """

    if not data:
        return None

    try:

        root = ET.fromstring(data)

    except Exception as e:

        print(
            "DB Änderungs-XML Fehler:",
            repr(e)
        )

        return None

    wanted_category = normalize(
        category
    ).upper()

    best_match = None
    best_difference = None

    for element in root.iter():

        tag = (
            element.tag
            .split("}")[-1]
            .lower()
        )

        if tag != "s":
            continue

        tl = None
        dp = None
        ar = None

        for child in element:

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

        if train_category != wanted_category:
            continue

        # A departure is what we're looking for.
        if dp is None:
            continue

        # For changes:
        # ct = changed time
        # pt = planned time
        db_time = (
            dp.get("ct", "").strip()
            or dp.get("pt", "").strip()
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

        difference = abs(
            (
                db_departure -
                planned_departure
            ).total_seconds()
        )

        difference_minutes = (
            difference / 60
        )

        if (
            difference_minutes
            > time_tolerance_minutes
        ):
            continue

        if (
            best_difference is None
            or difference < best_difference
        ):

            best_difference = difference

            best_match = (
                f"{train_category} "
                f"{train_number}"
            )

    return best_match

def lookup_db_train_by_time(
    category,
    station_name,
    planned_departure
):
    """
    Look up an IC/ICE/DPF train using DB Timetables.

    First checks the planned timetable (/plan).

    If no train is found, falls back to the full
    timetable changes feed (/fchg).

    The result is cached.
    """

    cache_key = (
        normalize(category),
        normalize(station_name),
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

                return cached.get("data")

    eva = config.DB_STATION_EVA

    if not eva:
        print(
            "DB_STATION_EVA ist nicht gesetzt."
        )

        return None

    # ==================================================
    # 1. TRY PLANNED TIMETABLE
    # ==================================================

    date_string = planned_departure.strftime(
        "%y%m%d"
    )

    hour = planned_departure.hour

    data = get_db_plan(
        eva,
        date_string,
        hour
    )

    result = parse_db_train_by_time(
        data,
        category,
        planned_departure
    )

    if result:

        print(
            f"DB Zug gefunden: {result} "
            f"(Plan {planned_departure.strftime('%H:%M')})"
        )

    # ==================================================
    # 2. TRY PREVIOUS HOUR
    # ==================================================

    if result is None:

        previous_hour = (
            planned_departure
            - timedelta(hours=1)
        )

        data = get_db_plan(
            eva,
            previous_hour.strftime("%y%m%d"),
            previous_hour.hour
        )

        result = parse_db_train_by_time(
            data,
            category,
            planned_departure
        )

    # ==================================================
    # 3. TRY NEXT HOUR
    # ==================================================

    if result is None:

        next_hour = (
            planned_departure
            + timedelta(hours=1)
        )

        data = get_db_plan(
            eva,
            next_hour.strftime("%y%m%d"),
            next_hour.hour
        )

        result = parse_db_train_by_time(
            data,
            category,
            planned_departure
        )

    # ==================================================
    # 4. FALL BACK TO FULL CHANGES
    # ==================================================

    if result is None:

        print(
            f"DB Plan leer / kein Treffer für "
            f"{category} um "
            f"{planned_departure.strftime('%H:%M')}"
        )

        change_data = get_db_changes(
            eva
        )

        result = parse_db_change_by_time(
            change_data,
            category,
            planned_departure
        )

        if result:

            print(
                f"DB Zug gefunden: {result} "
                f"(Änderung {planned_departure.strftime('%H:%M')})"
            )

    # ==================================================
    # CACHE RESULT
    # ==================================================

    with db_cache_lock:

        db_train_cache[cache_key] = {
            "timestamp": time.time(),
            "data": result
        }

    if result:

        print(
            f"DB Zug gefunden: "
            f"{result} "
            f"(um {planned_departure.strftime('%H:%M')})"
        )

    else:

        print(
            f"DB Zug nicht gefunden für "
            f"{category} um "
            f"{planned_departure.strftime('%H:%M')}"
        )

    return result

def get_hvv_data():
    url = config.HVV_API_URL + "/gti/public/departureList"
    now = datetime.now()

    payload = {
        "language": "de",
        "version": 63,
        "station": {
            "id": config.STATION_ID,
            "name": config.STATION_NAME,
            "type": "STATION"
        },
        "time": {
            "date": now.strftime("%d.%m.%Y"),
            "time": now.strftime("%H:%M")
        },
        "maxList": 10,
        "maxTimeOffset": 720,
        "useRealtime": True,
        "full": True,
        "showBroadcastRelevant": True
    }

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    headers = {
        "geofox-auth-user": credentials.HVV_API_USER,
        "geofox-auth-signature": get_signature(body),
        "geofox-auth-type": "HmacSHA1",
        "Content-Type": "application/json"
    }

    request = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (429, 503):
            err_code = str(e.code)
            print(f"HVV API HTTP Fehler {err_code} empfangen.")

            if e.code == 429:
                return [
                    {"linie": "", "ziel": "HTTP 429", "plan": "", "zeit": "", "nodata": True},
                    {"linie": "", "ziel": "TOO MANY", "plan": "", "zeit": "", "nodata": True},
                    {"linie": "", "ziel": "REQUESTS", "plan": "", "zeit": "", "nodata": True}
                ]
            else:  # 503
                return [
                    {"linie": "", "ziel": "HTTP 503", "plan": "", "zeit": "", "nodata": True},
                    {"linie": "", "ziel": "SERVICE", "plan": "", "zeit": "", "nodata": True},
                    {"linie": "", "ziel": "UNAVAILABLE", "plan": "", "zeit": "", "nodata": True}
                ]
        raise e

    result = []

    for dep in data.get("departures", []):
        delay_seconds = dep.get("delay")

        if delay_seconds is not None:
            delay = int(delay_seconds / 60)
            delay_found = True
        else:
            delay = 0
            delay_found = False

        offset = dep.get("timeOffset", 0)

        zeit = "sofort" if offset <= 0 else f"in {offset} Min"
        if dep.get("cancelled"):
            zeit = "fällt aus"

        target_time = now + timedelta(minutes=offset)
        planned_departure = target_time - timedelta(minutes=delay)
        plan_time = planned_departure.strftime("%H:%M")

        # Get line information FIRST
        line = dep.get("line", {})
        line_name = line.get("name", "").strip()
        line_direction = line.get("direction", "")

        # ==========================================
        # DB LOOKUP FÜR IC / ICE / DPF (NACH ZEIT)
        # ==========================================
        if line_name.upper() in ("ICE", "IC", "DPF"):
            try:
                db_name = lookup_db_train_by_time(
                    category=line_name,
                    station_name=config.STATION_NAME,
                    planned_departure=planned_departure
                )

                if db_name:
                    line_name = db_name

            except Exception as e:
                print(f"DB Lookup fehlgeschlagen für {line_name} um {plan_time}:", repr(e))

        # Die DB Infos müssen gar nicht ins result, da line_name jetzt korrekt ist.
        result.append({
            "station": {
                "id": config.STATION_ID,
                "name": config.STATION_NAME
            },
            "linie": line_name,
            "ziel": line_direction,
            "plan": plan_time,
            "zeit": zeit,
            "delay": delay,
            "delay_found": delay_found,
            "target_time": target_time
        })

    return result

def is_long_distance_train(line):
    line = normalize(line)

    return bool(re.fullmatch(
        r"(ICE|IC|DPF)\s*\d+",
        line
    ))


def get_db_station_eva(station_name):
    if not station_name:
        return None

    clean_name = station_name.strip()
    norm_search = normalize(clean_name).upper()

    # 1. READ DIRECTLY FROM CONFIG.PY
    # Checks if STATIONS / KNOWN_STATIONS / STATION_EVA exists in config
    for config_attr in ["STATION_EVA_MAP"]:
        station_dict = getattr(config, config_attr, None)
        if isinstance(station_dict, dict):
            # Check exact key match
            if clean_name in station_dict:
                return str(station_dict[clean_name])

            # Check case-insensitive / normalized match
            for key, val in station_dict.items():
                if normalize(str(key)).upper() == norm_search:
                    return str(val)

    # 2. CHECK RUNTIME CACHE
    with db_cache_lock:
        if norm_search in db_train_cache:
            cached = db_train_cache[norm_search]
            if cached.get("type") == "station":
                return cached.get("eva")

    # 3. FALLBACK TO DB API ONLY IF NOT IN CONFIG
    encoded_name = urllib.parse.quote(clean_name, safe="")
    data = db_api_get(f"/station/{encoded_name}")

    if data:
        try:
            root = ET.fromstring(data)
            for element in root.iter():
                eva_attr = element.get("eva")
                if eva_attr and eva_attr.isdigit():
                    with db_cache_lock:
                        db_train_cache[norm_search] = {
                            "type": "station",
                            "eva": eva_attr,
                            "timestamp": time.time()
                        }
                    return eva_attr
        except Exception as e:
            print("DB Station XML Fehler:", repr(e))

    print(f"Keine DB EVA-Nummer für '{station_name}' gefunden.")
    return None

def db_api_get(path):
    """
    Perform a GET request against the DB Timetables API.
    """

    url = config.DB_API_URL.rstrip("/") + "/" + path.lstrip("/")

    headers = {
        "DB-Client-ID": credentials.DB_CLIENT_ID,
        "DB-Api-Key": credentials.DB_API_KEY,
        "Accept": "application/xml",
        "User-Agent": "TransitMatrix"
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
                f"DB Content-Type: "
                f"{response.headers.get('Content-Type')}"
            )

            print(
                f"DB Response length: "
                f"{len(data)} bytes"
            )

            print(
                "DB Response:",
                data[:500]
            )

            return data

    except urllib.error.HTTPError as e:

        print(
            f"DB Timetables HTTP Fehler "
            f"{e.code}: {url}"
        )

        return None

    except Exception as e:

        print(
            f"DB Timetables Fehler: {repr(e)}"
        )

        return None

def get_db_station_eva(station_name):
    """
    Find the DB EVA number for a station name from config, cache, or API.
    """
    if not station_name:
        return None

    clean_name = station_name.strip()
    norm_search = normalize(clean_name).upper()

    # 1. READ DIRECTLY FROM CONFIG.PY
    for config_attr in ("STATION_EVA_MAP",):
        station_dict = getattr(config, config_attr, None)
        if isinstance(station_dict, dict):
            # Check exact key match
            if clean_name in station_dict:
                return str(station_dict[clean_name])

            # Check case-insensitive / normalized match
            for key, val in station_dict.items():
                if normalize(str(key)).upper() == norm_search:
                    return str(val)

    # 2. CHECK RUNTIME CACHE
    with db_cache_lock:
        if norm_search in db_train_cache:
            cached = db_train_cache[norm_search]
            if cached.get("type") == "station":
                return cached.get("eva")

    # 3. FALLBACK TO DB API ONLY IF NOT IN CONFIG
    encoded_name = urllib.parse.quote(clean_name, safe="")
    data = db_api_get(f"/station/{encoded_name}")

    if not data:
        print(f"Keine DB EVA-Nummer für '{station_name}' gefunden.")
        return None

    try:
        root = ET.fromstring(data)
    except Exception as e:
        print("DB Station XML konnte nicht gelesen werden:", repr(e))
        return None

    eva = None
    for element in root.iter():
        tag = element.tag.lower()
        eva_attr = element.get("eva") or (element.text.strip() if element.text else None)
        if (tag.endswith("eva") or tag.endswith("evanumber") or element.get("eva")) and eva_attr and eva_attr.isdigit():
            eva = eva_attr
            break

    if eva:
        with db_cache_lock:
            db_train_cache[norm_search] = {
                "type": "station",
                "eva": eva,
                "timestamp": time.time()
            }
        print(f"DB Station gefunden: {station_name} -> EVA {eva}")
        return eva

    print(f"Keine DB EVA-Nummer für '{station_name}' gefunden.")
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
        f"DB Timetable: Lade {eva_no} "
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

    /fchg/{evaNo} contains known timetable changes
    from now into the future.
    """

    cache_key = str(eva_no)

    with db_cache_lock:

        cached = db_fchg_cache.get(cache_key)

        if cached:

            age = time.time() - cached["timestamp"]

            cache_time = getattr(
                config,
                "DB_FCHG_CACHE_TIME",
                30
            )

            if age < cache_time:
                return cached["data"]

    path = f"/fchg/{eva_no}"

    print(
        f"DB Timetable: Lade Änderungen {eva_no}"
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

def parse_db_train(data, category, target_time):

    if not data:
        return None

    try:
        root = ET.fromstring(data)

    except Exception as e:

        print(
            "DB Timetable XML Fehler:",
            repr(e)
        )

        return None

    wanted_number = str(train_number)

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
                f"{category} {wanted_number}"
            )
            or normalized == normalize(
                f"{category}{wanted_number}"
            )
            or normalized == wanted_number
        ):
            candidates.append(element)

    if not candidates:
        return None

    result = {
        "category": category,
        "number": train_number,
        "name": f"{category} {train_number}",
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

            # train number/name
            if (
                tag.endswith("tl")
                or tag.endswith("n")
            ):

                if (
                    category in normalize(text)
                    or text == train_number
                ):
                    result["name"] = text

            # destination
            elif tag.endswith("dp"):

                result["destination"] = text

            # origin
            elif tag.endswith("ar"):

                result["origin"] = text

            # platform
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
    Look up an IC/ICE/DPF train using DB Timetables.

    The result is cached so the same train is not repeatedly
    requested from DB.
    """

    if target_time is None:
        target_time = datetime.now()

    cache_key = (
        normalize(category),
        str(train_number),
        normalize(station_name),
        target_time.strftime("%Y%m%d%H%M")
    )

    with db_cache_lock:
        cached = db_train_cache.get(cache_key)

        if cached:
            age = time.time() - cached["timestamp"]

            if age < config.DB_CACHE_TIME:
                return cached.get("data")

    eva = config.DB_STATION_EVA

    if not eva:
        return None

    date_string = target_time.strftime("%Y%m%d")
    hour = target_time.hour

    data = get_db_plan(
        eva,
        date_string,
        hour
    )

    result = parse_db_train(
        data,
        category,
        train_number
    )

    # The train might be close to an hour boundary.
    if result is None:

        previous_hour = target_time - timedelta(hours=1)
        next_hour = target_time + timedelta(hours=1)

        # Previous hour
        if previous_hour.date() == target_time.date():

            data = get_db_plan(
                eva,
                previous_hour.strftime("%Y%m%d"),
                previous_hour.hour
            )

            result = parse_db_train(
                data,
                category,
                train_number
            )

        # Next hour
        if result is None:

            if next_hour.date() == target_time.date():

                data = get_db_plan(
                    eva,
                    next_hour.strftime("%Y%m%d"),
                    next_hour.hour
                )

                result = parse_db_train(
                    data,
                    category,
                    train_number
                )

    with db_cache_lock:
        db_train_cache[cache_key] = {
            "timestamp": time.time(),
            "data": result
        }

    if result:
        print(
            f"DB Zug gefunden: "
            f"{category} {train_number}"
        )
    else:
        print(
            f"DB Zug nicht gefunden: "
            f"{category} {train_number}"
        )

    return result

def get_announcements():
    url = config.HVV_API_URL + "/gti/public/getAnnouncements"

    payload = {
        "language": "de",
        "version": 63,
        "names": ["RE7", "RE70", "782", "185", "X95"],
        "full": True,
        "showBroadcastRelevant": True,
    }

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    headers = {
        "geofox-auth-user": credentials.HVV_API_USER,
        "geofox-auth-signature": get_signature(body),
        "geofox-auth-type": "HmacSHA1",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, data=body, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code in (429, 503):
            err_code = e.response.status_code
            print(f"Announcements HTTP Fehler {err_code} empfangen.")

            detail_text = "TOO MANY REQUESTS" if err_code == 429 else "SERVICE UNAVAILABLE"

            return {
                "announcements": [
                    {
                        "id": f"HTTP_{err_code}",
                        "description": f"HTTP FEHLER {err_code} - {detail_text}",
                        "locations": []
                    }
                ]
            }
        raise e

def parse_announcements(data):

    result = []

    for announcement in data.get("announcements", []):

        text = announcement.get(
            "description",
            ""
        ).strip()

        locations = []

        for loc in announcement.get("locations", []):

            line = loc.get("line")

            if not line:
                continue

            locations.append({
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
            })

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

def parse(text):

    soup = BeautifulSoup(text, "html.parser")

    result = []

    # alle Zeilen aus departure-list holen
    rows = soup.select(".departure-list .row")
    debug_print("Rows gefunden:", len(rows))

    if not rows:
        print(soup.prettify()[:5000])


    for row in rows:

        cells = [
            c.get_text(" ", strip=True)
            for c in row.find_all("div", recursive=False)
        ]

        # Kopfzeile überspringen
        if not cells:
            continue

        if cells[0].lower() == "linie":
            continue

        # Datumzeilen ignorieren
        if re.match(
                r"\d{1,2}\.\s+[A-Za-zäöüÄÖÜ]+\s+\d{4}",
                cells[0]
        ):
            continue

        # mindestens Linie + Ziel + Zeit benötigt
        if len(cells) < 3:
            continue

        debug_print("CELLS:", cells)
        debug_print(
            "ZEIT FELD:",
            repr(cells[3]) if len(cells) > 3 else "NICHT VORHANDEN"
        )
        debug_print("RAW CELLS:", cells)
        linie = cells[0].strip()
        ziel = cells[1].strip()

        if len(cells) >= 5:
            plan = cells[3].strip()
            zeit = cells[4].strip()

        else:
            # Einfache Abfahrtsliste ohne Gleis/Echtzeit
            plan = cells[2].strip()
            zeit = cells[2].strip()

        # Tippfehler von WEB abfangen
        if zeit.lower().strip() == "sofor":
            zeit = "sofort"

        # Ausfälle niemals überschreiben
        is_cancelled = "fällt aus" in zeit.lower()

        # Wenn keine "in XX Min" Angabe vorhanden ist,
        # Minuten aus der Planzeit berechnen
        if (
                not is_cancelled
                and not re.search(r"\d+\s*Min", zeit, re.IGNORECASE)
        ):

            match = re.search(
                r"(\d{1,2}):(\d{2})",
                plan
            )

            if match:

                hour = int(match.group(1))
                minute = int(match.group(2))

                now = datetime.now()

                departure = now.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0
                )

                diff_seconds = (
                        departure - now
                ).total_seconds()

                # Falls die Abfahrtszeit bereits vorbei ist,
                # prüfen ob es tatsächlich die nächste Abfahrt
                # am nächsten Tag ist.
                if diff_seconds < -60:
                    departure += timedelta(days=1)
                    diff_seconds = (
                            departure - now
                    ).total_seconds()

                    target_time = departure

                # Unter einer Minute = sofort
                if diff_seconds <= 60:
                    zeit = "sofort"
                else:
                    # immer auf die nächste volle Minute aufrunden
                    diff = math.ceil(diff_seconds / 60)
                    zeit = f"in {diff} Min"

            else:
                # wirklich keine Zeit vorhanden
                zeit = plan

        # SEV + Liniennummer behalten
        sev_match = re.match(
            r"SEV\s+([A-Z]*\d+)",
            linie,
            re.IGNORECASE
        )

        if sev_match:
            linie = "SEV " + sev_match.group(1).upper()

        # Zusatztexte hinter der eigentlichen Linienkennung entfernen
        linie = re.sub(r"^(.*?\d+).*", r"\1", linie).strip()

        match = re.fullmatch(
            r"(MEX|ALX|FLX|FEX|ICE|ECE|IRE|ZUG|AST|KAT|SCH|SEV|RNV|AT|CB|RS|RE|RB|RJ|NJ|EN|GI|IC|IR|LM|EC|EV|FM|SB|TB|HS|S|U|A|C|X|M|N|R|F)(?:[\s-]*([A-Z]*\d+))?",
            linie,
            re.IGNORECASE
        )

        if match:

            typ = match.group(1).upper()
            nummer = match.group(2)

            if nummer and nummer.upper() != "NONE":

                if typ == "GI":
                    linie = f"{typ}-{nummer}"

                elif typ in ["ICE", "ECE", "IC", "EC", "NJ", "EN", "ZUG", "SEV"]:
                    linie = f"{typ} {nummer}"

                else:
                    linie = f"{typ}{nummer}"

            else:
                linie = typ

        # DRF Fernreisezug:
        # DB lookup versuchen, falls die Linie von HVV nicht
        # genauer identifiziert werden kann.
        drf_match = re.fullmatch(
            r"DRF\s+(\d+)",
            linie,
            re.IGNORECASE
        )

        if drf_match:
            zugnummer = drf_match.group(1)

            db_linie = lookup_db_train(
                train_number=zugnummer,
                planned_time=plan,
                destination=ziel
            )

            if db_linie:
                linie = db_linie
                debug_print(
                    "DRF DB Lookup:",
                    zugnummer,
                    "->",
                    linie
                )
            else:
                linie = "ZUG " + zugnummer
                debug_print(
                    "DRF DB Lookup:",
                    zugnummer,
                    "-> kein Ergebnis, verwende ZUG"
                )

        debug_print(
            "GELESEN:",
            linie,
            "|",
            ziel,
            "|",
            plan,
            "|",
            zeit
        )

        # Linienzusätze entfernen
        linie = re.sub(
            r"\s*\(.*?\)",
            "",
            linie
        ).strip()

        # Linie prüfen
        if not is_line(linie):
            debug_print("Übersprungen:", linie)
            continue


        delay = 0

        # Verspätung aus Planzeit
        delay_match = re.search(
            r"\+\s*[^0-9]*?(\d+)",
            plan.replace("\xa0", " ")
        )

        if delay_match:
            delay = int(delay_match.group(1))
            delay_found = True
        else:
            delay_found = False

        # ==========================================
        # NEU: TARGET TIME BERECHNEN (Für Live-Countdown)
        # ==========================================
        target_time = None
        if "fällt aus" not in zeit.lower():
            # 1. Versuch: Aus Planzeit + Verspätung berechnen
            match_plan = re.search(r"(\d{1,2}):(\d{2})", plan)
            if match_plan:
                now = datetime.now()
                dep_time = now.replace(
                    hour=int(match_plan.group(1)),
                    minute=int(match_plan.group(2)),
                    second=0,
                    microsecond=0
                )
                # Falls die Zeit in der Vergangenheit liegt -> Tageswechsel
                if (dep_time - now).total_seconds() < -60:
                    dep_time += timedelta(days=1)

                # Verspätung addieren
                target_time = dep_time + timedelta(minutes=delay)

            # 2. Versuch: Falls WEB keine Planzeit, aber "in 5 Min" liefert
            else:
                match_min = re.search(r"(\d+)\s*Min", zeit, re.IGNORECASE)
                if match_min:
                    target_time = datetime.now() + timedelta(minutes=int(match_min.group(1)))
                elif "sofort" in zeit.lower() or "sofor" in zeit.lower():
                    target_time = datetime.now()

        result.append({
            "station": {
                "id": config.STATION_ID,
                "name": config.STATION_NAME
            },
            "linie": linie,
            "ziel": ziel,
            "plan": plan,
            "delay": delay,
            "delay_found": delay_found,
            "zeit": zeit,
            "target_time": target_time  # <--- HIER WIRD ES ÜBERGEBEN
        })

    print("Gefundene Abfahrten:", len(result))

    return result

def draw_no_departures(matrix):

    global no_departures_blink
    global data_status

    if not no_departures_blink:
        return

    if data_status == "OFFLINE":

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


    total_height = len(lines) * config.CHAR_HEIGHT + (len(lines)-1) * 4

    start_y = (config.HEIGHT - total_height) // 2


    for i, text in enumerate(lines):

        width = len(text) * config.CHAR_WIDTH

        x = (config.WIDTH - width) // 2

        y = start_y + i * (config.CHAR_HEIGHT + 4)

        draw_text(
            matrix,
            x,
            y,
            text
        )

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
        prefix = "!" + ",".join(lines) + "!: "
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
        line_names = [loc.get("line", "") if isinstance(loc, dict) else str(loc) for loc in lines]
        header = "!" + ",".join(line_names) + "!:"
    else:
        header = "!MELDUNG!:"

    # ==========================================
    # ZÄHLER LOGIK (z.B. "1/2")
    # ==========================================
    total_msgs = len(messages)
    show_counter = False
    counter_text = ""
    counter_width = 0

    if total_msgs > 1:
        # Zähler für 2 Sekunden anzeigen, dann 3 Sekunden ausblenden
        if int(time.time()) % 5 >= 3:
            show_counter = True
            counter_text = f"{current_message + 1}/{total_msgs}"
            counter_width = get_text_width(counter_text)

    # Berechnen, wie viel Platz für den Header bleibt
    available_pixels = config.WIDTH
    if show_counter:
        available_pixels -= (counter_width + 2) # Platz für Zähler + etwas Abstand abziehen

    max_header_chars = available_pixels // config.CHAR_WIDTH

    # ==========================================
    # KOPFZEILE (LINIEN) ZEICHNEN
    # ==========================================
    if get_text_width(header) > available_pixels:
        header_display = get_scroll_text(
            header,
            message_scroll_offset,
            max_header_chars
        )
    else:
        header_display = header

    # Kopfzeile in Rot (ColorCode.DELAY)
    draw_text(matrix, 0, 48, header_display, config.ColorCode.DELAY)

    # Zähler einblenden (in Gelb, damit er sich abhebt)
    if show_counter:
        counter_x = config.WIDTH - counter_width
        draw_text(matrix, counter_x, 48, counter_text, config.ColorCode.DEFAULT)

    # ==========================================
    # MELDUNGSTEXT SCROLLEN
    # ==========================================
    text = normalize(msg.get("text", "")) + " +++ "
    text_scroll = get_scroll_text(
        text,
        message_scroll_offset,
        10
    )
    draw_text(matrix, 0, 56, text_scroll, config.ColorCode.DELAY)

def get_web_data():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0)"
        }

        request = urllib.request.Request(
            config.WEB_URL,
            headers=headers
        )

        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode("utf-8")

    except Exception as e:
        print(f"Fehler beim Laden der Webseite: {e}")
        return None
# DISPLAY

def draw_reload_bar(matrix):

    global reload_progress
    global data_status

    # letzte Zeile löschen
    for x in range(config.WIDTH):
        set_pixel(
            matrix,
            x,
            config.HEIGHT - 1,
            0
        )

    # Farbe abhängig vom Verbindungsstatus
    if data_status == "OFFLINE":
        bar_color = config.ColorCode.DELAY
    else:
        bar_color = config.ColorCode.OK

    # Fortschrittsbalken
    for x in range(reload_progress):
        set_pixel(
            matrix,
            x,
            config.HEIGHT - 1,
            bar_color
        )

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

    if bus_data and bus_data[0].get("nodata"):
        draw_no_departures(matrix)
    else:
        max_departures = 3 if show_station_header else 4

        # ÄNDERUNG: Wenn Meldungen da sind, IMMER auf 3 begrenzen
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

    # immer anzeigen
    draw_reload_bar(matrix)
    show_matrix(matrix)
# DATEN

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
        print("Lade Abfahrten...")
        data = []

        try:
            if config.DATA_SOURCE == "WEB":
                page = get_web_data()

                if page is None:
                    data_status = "OFFLINE"
                    data = []
                else:
                    data = parse(page)
                    data_status = "OK" if data else "EMPTY"

            elif config.DATA_SOURCE == "HVV":
                data = get_hvv_data()
                data_status = "OK"

        except Exception as e:
            print("FEHLER BEIM LADEN DER DATEN:", repr(e))
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
def update_messages():
    global messages
    global line_announcements

    try:
        data = get_announcements()

        parsed = parse_announcements(data)

        # Alle Meldungen für den Meldungsticker
        messages = parsed

        # Unabhängig davon für das ! an den Abfahrten
        line_announcements = parsed

        print(
            "Meldungen geladen:",
            len(messages)
        )

        for announcement in line_announcements:
            print(
                "  Meldung:",
                announcement.get("text", "")[:100]
            )

            for location in announcement.get("lines", []):
                print(
                    "    Linie:",
                    location.get("line"),
                    "| Richtung:",
                    location.get("direction"),
                    "| beide:",
                    location.get("bothDirections")
                )

    except Exception as e:

        print(
            "Meldungen konnten nicht geladen werden:",
            e
        )

        messages = []
        line_announcements = []


def update_messages_loop():

    while True:

        print("Lade Meldungen...")

        update_messages()

        time.sleep(config.DATA_UPDATE)

# ZENTRALER ANIMATIONS- & RENDER-TAKT

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
            f"Helligkeit auf {brightness}% gesetzt"
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

        # Verspätung ignorieren wenn bereits NOW
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

        # RELOAD-BALKEN
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

                # Platz für Linienanzeige ermitteln (34 Pixel)
                line_pixel_space = config.WIDTH - (5 * config.CHAR_WIDTH)

                for i, bus in enumerate(bus_data[:max_departures]):
                    # Linien-Scrollen (FIX: Exakt an UI-Breite angepasst)
                    line = normalize(bus.get("linie", ""))
                    if get_text_width(line) > line_pixel_space:
                        line_scroll_offset[i] += 1
                        if line_scroll_offset[i] >= len(line + "   "):
                            line_scroll_offset[i] = 0

                    # Ziel-Scrollen
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

        # INFO-MELDUNG SCROLLEN (FIX: Aus der Einrückung des Dep-Scrollings befreit)
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

        # NORMALES BLINKEN
        if current_time - last_blink_time >= blink_interval:
            last_blink_time = current_time
            blink_state = not blink_state
            needs_redraw = True

        # BLINKEN BEI KEINEN ABFAHRTEN
        if bus_data and bus_data[0].get("nodata"):
            if current_time - last_no_departures_blink >= no_data_blink_interval:
                last_no_departures_blink = current_time
                no_departures_blink = not no_departures_blink
                needs_redraw = True

        # ZEIT / MINUTEN WECHSEL
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
                print("Render Fehler:", repr(e))
                time.sleep(1)
                continue

        time.sleep(0.05)

# TEXT NORMALISIEREN

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

    if config.DISPLAY_MODE == "LED":
        init_led()
    elif config.DISPLAY_MODE == "WINDOW":
        create_window()
    else:
        raise ValueError(f"Invalid DISPLAY_MODE: {config.DISPLAY_MODE}")

    # 1. Start the main data thread
    threading.Thread(target=update_data, daemon=True).start()

    # 2. Start the messages thread ONLY if using HVV
    if config.DATA_SOURCE == "HVV":
        threading.Thread(target=update_messages_loop, daemon=True).start()

    # 3. Start the animation/render loop
    threading.Thread(target=master_render_loop, daemon=True).start()

    # 4. Keep the program running
    if config.DISPLAY_MODE == "WINDOW" and window:
        window.mainloop()
    elif config.DISPLAY_MODE == "LED":
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nProgram stopped.")
            sys.exit(0)