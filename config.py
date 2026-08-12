# config.py for TransitMatrix.py
# Contact Fluffy_Nardoragon@mail.de or https://github.com/alfi-floof/TransitMatrix/issues
from enum import IntEnum
# ==========================
# EINSTELLUNGEN
# ==========================
STATION_NAME = "Frankfurt (Main) Hbf"
STATION_ID = "8000105"
DATA_SOURCE = "HVV"
# später: DATA_SOURCE = "HVV"
# "HVV" = API | "WEB" = Scraping

# ==========================
# AUSGABE
# ==========================
DISPLAY_MODE = "WINDOW"
# "WINDOW" = PC Desktop Vorschau
# "LED" = echte RGB LED Matrix über GPIO

WEB_URL = f"https://www.vrt-info.de/DM/{STATION_ID}"

HVV_API_URL = "https://gti.geofox.de"

# ==========================
# DB TIMETABLES API
# ==========================
DB_API_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
DB_STATION_EVA = "8000105"

# DB Timetables lookup cache lifetime in seconds
DB_CACHE_TIME = 3600
DB_CACHE_TIME = 300
DB_FCHG_CACHE_TIME = 30

DATA_UPDATE = 20

DEBUG = True

WIDTH = 64  # Changing this currently requires modifications in multiple parts of the code, as 64x64 is currently hard-coded in several places.
HEIGHT = 64  # Changing this currently requires modifications in multiple parts of the code, as 64x64 is currently hard-coded in several places.

SCALE = 5
FONT_SCALE = 1

CHAR_WIDTH = 6
CHAR_HEIGHT = 7
LINE_HEIGHT = 8

DAY_BRIGHTNESS = 80      # tagsüber (0-100)
NIGHT_BRIGHTNESS = 10    # nachts (0-100)


NIGHT_START = 21         # ab 21:00 dimmen
NIGHT_END = 7            # bis 07:00

# ==========================
# FARBEN
# ==========================
class ColorCode(IntEnum):
    DEFAULT = 1
    DELAY   = 2
    OK      = 3
    SBAHN   = 4
    UBAHN   = 5
    AKN   = 6
    WHITE   = 7
    SEV     = 8
    REGIO   = 9
    MESSAGE = 10
    FLX = 11

LINE_COLORS = {
    "SEV":  ColorCode.SEV,
    "FLX":  ColorCode.FLX,

    "ICE":  ColorCode.WHITE,
    "ECE":  ColorCode.WHITE,
    "IC":   ColorCode.WHITE,
    "EC":   ColorCode.WHITE,
    "RJ":   ColorCode.WHITE,
    "NJ":   ColorCode.WHITE,

    "RE":   ColorCode.REGIO,
    "RB":   ColorCode.REGIO,

    "S":    ColorCode.SBAHN,
    "U":    ColorCode.UBAHN,
    "A":    ColorCode.AKN,
}

STATUS_COLORS = {
    "DEFAULT": ColorCode.DEFAULT,
    "DELAY": ColorCode.DELAY,
    "OK": ColorCode.OK,
    "MESSAGE": ColorCode.MESSAGE,
}

HEX_COLORS = {
    ColorCode.DEFAULT: "#cca300",
    ColorCode.DELAY:   "#FF0000",
    ColorCode.OK:      "#00FF00",
    ColorCode.SBAHN:   "#007A33",
    ColorCode.UBAHN:   "#0064B3",
    ColorCode.AKN:     "#FFA500",
    ColorCode.SEV:     "#9D1962",
    ColorCode.REGIO:   "#880000",
    ColorCode.WHITE:   "#FFFFFF",
    ColorCode.MESSAGE: "#FF0000",
    ColorCode.FLX:     "#73D700",
}

STATION_EVA_MAP = {
    "HAMBURG HBF": "8002549",
    "HAMBURG-HARBURG": "8000147",
    "HAMBURG-DAMMTOR": "8002548",
    "ELMSHORN": "8000092",
    "NEUMÜNSTER": "8000273",
    "KIEL HBF": "8000199",
    "BERLIN HBF": "8011160",
    "BREMEN HBF": "8000050",
    "HANNOVER HBF": "8000152",
    "MÜNCHEN HBF": "8000261",
    "ERFURT HBF": "8010101",
    "ROSTOCK HBF": "8010304"
}

if __name__ == "__main__":
    print("This file only contains configuration settings.")
    print("To start TransitMatrix, run TransitMatrix.py.")
