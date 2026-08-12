# TransitMatrix
## README.md
### If you have Questions or Ideas contact Fluffy_Nardoragon@mail.de or [TransitMatrix/issues](https://github.com/alfi-floof/TransitMatrix.py/issues)

TransitMatrix is a real-time public transit departure board built for 64x64 RGB LED matrices powered by a Raspberry Pi. It fetches live departure times, service disruptions, and delays from APIs (HVV, Deutsche Bahn) or web sources, displaying them on a 64x64 matrix display or a PC desktop preview window.

### Required Hardware
- Raspberry Pi (I'm using a Pi 4 4GB)
- A LED Matrix compatible with the RPi (I'm using a [SEENGREAT RGB Matrix P3.0 64x64](https://seengreat.com/wiki/74/rgb-matrix-p3-0-64x64))
  - You can use a Adafruit RGB Matrix Bonnet, i wired the Display straight to the GPIO Pins of my Pi. **This will requrire Code Changes!**
- 5V 3A+ power supply (Check your Panel)

## Quick Start & Installation

### 1. Clone the Repository
```Bash
git clone https://github.com/alfi-floof/TransitMatrix.git
cd TransitMatrix
```

### 2. Install Python Dependencies
```Bash
python -m pip install -r requirements.txt
```

### 3. Launch TransitMatrix
To start the display application, make sure you have adjused the ``Config.py`` to your liking, then start it. Keep in mind the LED Mode needs root Access for the GPIO.

``python TransitMatrix.py
/
sudo python TransitMatrix.py``


```python
# config.py for TransitMatrix.py
# Contact: Fluffy_Nardoragon@mail.de or https://github.com/alfi-floof/TransitMatrix/issues

from enum import IntEnum

# ==============================================================================
# STATION & DATA SOURCE SETTINGS
# ==============================================================================

# Explanation: Used by the DB API.
STATION_NAME = ""

# Explanation: Station identifier code used by the HVV API or WEB Scraping.
STATION_ID = ""

# Explanation: Specifies where departure data is retrieved from:
# - "HVV": Fetches data via the HVV Geofox GTI API (Requires API credentials below).
# - "WEB": Fetches data via web scraping.
DATA_SOURCE = ""


# ==============================================================================
#  DISPLAY & OUTPUT MODE
# ==============================================================================

# Explanation: Determines where the display output is rendered:
# - "LED": Drives physical RGB LED matrix panels via Raspberry Pi GPIO.
# - "WINDOW": Launches an interactive Tkinter PC desktop preview simulator for testing.
DISPLAY_MODE = "LED"

# Explanation: Scraping URL generated dynamically using STATION_ID.
WEB_URL = f"https://.../DM/{STATION_ID}"


# ==============================================================================
#  HVV GEOFOX GTI API URL
# ==============================================================================

# Explanation: Endpoint URL for the HVV Geofox GTI service.
HVV_API_URL = "https://gti.geofox.de"


# ==============================================================================
#  DEUTSCHE BAHN (DB) TIMETABLES API URL
# ==============================================================================

# Explanation: Base endpoint for Deutsche Bahn Timetables API v1 (Marketplace API).
DB_API_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"

# Explanation: Cache retention time in seconds for DB station lookups (3600 sec = 1 hour).
# Helps avoid exceeding rate limits on DB APIs.
DB_CACHE_TIME = 3600

# ==============================================================================
#  RUNTIME & DISPLAY GEOMETRY
# ==============================================================================

# Polling frequency in seconds for updating departure data from APIs.
DATA_UPDATE = 20

# Enable verbose debug output in console logs (True/False).
DEBUG = True

# Width of the LED Matrix display in pixels.
# NOTE: Layout positioning is currently hard-coded for 64x64 resolution.
WIDTH = 64

# Height of the LED Matrix display in pixels.
# NOTE: Layout positioning is currently hard-coded for 64x64 resolution.
HEIGHT = 64

# Scaling multiplier for the desktop window preview mode ("WINDOW" mode).
SCALE = 5

# Scaling multiplier for bitmap font rendering.
FONT_SCALE = 1

# Character pixel dimensions and line height spacing for the custom bitmap font.
CHAR_WIDTH = 6
CHAR_HEIGHT = 7
LINE_HEIGHT = 8


# ==============================================================================
#  AUTOMATIC NIGHT DIMMING & BRIGHTNESS
# ==============================================================================

# LED brightness level (0% - 100%) during daytime hours.
DAY_BRIGHTNESS = 80

# LED brightness level (0% - 100%) during nighttime hours to prevent glare.
NIGHT_BRIGHTNESS = 10

# Hour (24-hour clock) when night dimming begins.
NIGHT_START = 21

# Hour (24-hour clock) when night dimming ends.
NIGHT_END = 7


# ==============================================================================
#  COLOR SCHEMES & LINE MAPPINGS
# ==============================================================================

class ColorCode(IntEnum):
    DEFAULT = 1
    DELAY   = 2
    OK      = 3
    SBAHN   = 4
    UBAHN   = 5
    AKN     = 6
    WHITE   = 7
    SEV     = 8
    REGIO   = 9
    MESSAGE = 10
    FLX     = 11


# Explanation: Maps transit line prefixes (S, U, RE, ICE, SEV, etc.) to specific ColorCodes.
LINE_COLORS = {
    "SEV":  ColorCode.SEV,      # Replacement Rail Bus (Schienenersatzverkehr)
    "FLX":  ColorCode.FLX,      # FlixTrain

    # Long-Distance Express Trains (White)
    "ICE":  ColorCode.WHITE,  
    "ECE":  ColorCode.WHITE,
    "IC":   ColorCode.WHITE,
    "EC":   ColorCode.WHITE,
    "RJ":   ColorCode.WHITE,
    "NJ":   ColorCode.WHITE,

    # Regional Transit
    "RE":   ColorCode.REGIO,    
    "RB":   ColorCode.REGIO,

    # Rapid Transit
    "S":    ColorCode.SBAHN, 
    "U":    ColorCode.UBAHN, 
    "A":    ColorCode.AKN,      
}

# Color mappings for dynamic operational states and notifications.
STATUS_COLORS = {
    "DEFAULT": ColorCode.DEFAULT,
    "DELAY": ColorCode.DELAY,
    "OK": ColorCode.OK,
    "MESSAGE": ColorCode.MESSAGE,
}

#Maps each ColorCode ID to a specific Hexadecimal RGB color value.
HEX_COLORS = {
    ColorCode.DEFAULT: "#cca300",  # Amber/Yellow
    ColorCode.DELAY:   "#FF0000",  # Red
    ColorCode.OK:      "#00FF00",  # Bright Green
    ColorCode.SBAHN:   "#007A33",  # S-Bahn Green
    ColorCode.UBAHN:   "#0064B3",  # U-Bahn Blue
    ColorCode.AKN:     "#FFA500",  # Orange
    ColorCode.SEV:     "#9D1962",  # Magenta
    ColorCode.REGIO:   "#880000",  # DB Red
    ColorCode.WHITE:   "#FFFFFF",  # Pure White
    ColorCode.MESSAGE: "#FF0000",  # Warning Red
    ColorCode.FLX:     "#73D700",  # Flix Green
}

# Dictionary mapping major German station names to their 7-digit Deutsche Bahn EVA station IDs, Needs to be adjused to your Station for FLX,IC,ICE ID Lookup
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
```

## Questions, Feedback & Issues

Have an idea for a feature or found a bug?
    Open an Issue: [TransitMatrix/issues](https://github.com/alfi-floof/TransitMatrix.py/issues)
    Email Contact: Fluffy_Nardoragon@mail.de
