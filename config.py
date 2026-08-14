# config.py for TransitMatrix.py
# Contact Fluffy_Nardoragon@mail.de or https://github.com/alfi-floof/TransitMatrix/issues
from enum import IntEnum
# ==========================
# SETTINGS
# ==========================
STATION_NAME = "Hamburg Hbf"
STATION_ID = ""
DB_STATION_EVA = "8002548"

DATA_SOURCE = "HVV"

# ==========================
# OUTPUT
# ==========================
DISPLAY_MODE = "WINDOW"
# "WINDOW" = PC Desktop Vorschau
# "LED" = echte RGB LED Matrix über GPIO

HVV_API_URL = "https://gti.geofox.de"

# ==========================
# DB TIMETABLES API
# ==========================
DB_API_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"

# DB Timetables lookup cache lifetime in seconds
DB_CACHE_TIME = 3600
DB_FCHG_CACHE_TIME = 30

DATA_UPDATE = 20

DEBUG = False

WIDTH = 64  # Changing this currently requires modifications in multiple parts of the code, as 64x64 is currently hard-coded in several places.
HEIGHT = 64  # Changing this currently requires modifications in multiple parts of the code, as 64x64 is currently hard-coded in several places.

SCALE = 5
FONT_SCALE = 1

CHAR_WIDTH = 6
CHAR_HEIGHT = 7
LINE_HEIGHT = 8

DAY_BRIGHTNESS = 80      # at daytime (0-100)
NIGHT_BRIGHTNESS = 10    # at nighttime (0-100)


NIGHT_START = 21         # Dim from 21:00
NIGHT_END = 7            # until 07:00

MONITORED_LINES = [ # Hard-coded lines for monitoring announcements
    "RE7",
    "RE70",
    "782-AK",
    "185",
    "X95",
    "6502",
]

ANNOUNCEMENT_LINE_CACHE_TIME = 3600  # Monitors the defined lines and checks cached departures for those lines, including announcements affecting them for up to (3600 sec = 1 hour) ahead.


# ==========================
# Colors
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
    ColorCode.FLX:     "#76E806",
}

if __name__ == "__main__":
    print("This file only contains configuration settings.")
    print("To start TransitMatrix, run TransitMatrix.py.")
