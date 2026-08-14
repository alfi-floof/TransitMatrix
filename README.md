# TransitMatrix
## README.md
### If you have Questions or Ideas contact Fluffy_Nardoragon@mail.de or [TransitMatrix/issues](https://github.com/alfi-floof/TransitMatrix.py/issues)

TransitMatrix is a real-time public transit departure board built for 64x64 RGB LED matrices powered by a Raspberry Pi. It fetches live departure times, service disruptions, and delays from the HVV API displaying them on a 64x64 matrix display or a PC desktop preview window. Since the HVV API dosn't deliver ICE/IC Numbers, those get pulled from the DB Timetables API.

### Required Hardware
- Raspberry Pi (I'm using a Pi 4 4GB)
- A LED Matrix compatible with the RPi (I'm using a [SEENGREAT RGB Matrix P3.0 64x64](https://seengreat.com/wiki/74/rgb-matrix-p3-0-64x64))
  - You can use a Adafruit RGB Matrix Bonnet, i wired the Display straight to the GPIO Pins of my Pi. **Using a different display or connection method will require code changes!**
- 5V 3A+ power supply (Check your Panel)

### Required APIs 
- [HVV Geofox-API](https://www.hvv.de/de/fahrplaene/abruf-fahrplaninfos/datenabruf) - (You will need to Contact the HVV API Team at api@hochbahn.de)
- [DB Timetables API](https://developers.deutschebahn.com/db-api-marketplace/apis/product/160163) - (You will need to Create a DB Customer Account)

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
### 3. Rename ``credentials.py.example`` to ``credentials.py``
Linux/Unix: ```mv credentials.py.example credentials.py```
Windows: ```ren credentials.py.example credentials.py```


### 4. Add Credentials to ``credentials.py``

```python
#HVV GeoFox API
HVV_API_USER = ""
HVV_API_PASSWORD = ""

# DB Timetables API
DB_CLIENT_ID = ""
DB_API_KEY = ""
```

### 4. Launch TransitMatrix
To start the display application, make sure you have adjused the ``config.py`` to your liking, then start it. Keep in mind the LED Mode needs root Access for the GPIO.

``python TransitMatrix.py
/
sudo python TransitMatrix.py``


## Questions, Feedback & Issues

Have an idea for a feature or found a bug?
    Open an Issue: [TransitMatrix/issues](https://github.com/alfi-floof/TransitMatrix.py/issues)
    Email Contact: Fluffy_Nardoragon@mail.de
