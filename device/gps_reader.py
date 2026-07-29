# device/gps_reader.py
"""Reads NMEA sentences from Beitian BN-880 on UART and exposes latest fix.
"""
import threading
import time
import serial
import os
import pynmea2

GPS_DEVICES = [os.environ.get("GPS_DEVICE", "/dev/ttyS0"), "/dev/ttyAMA0"]
BAUD = int(os.environ.get("GPS_BAUD", 9600))

class GPSReader(threading.Thread):
    def __init__(self, device=None, baud=BAUD):
        super().__init__(daemon=True)
        self.device = device
        self.baud = baud
        self.running = False
        self.latest = {
            'lat': None,
            'lon': None,
            'speed_mps': None,
            'track': None,
            'ts': None
        }
        self._ser = None

    def open_port(self):
        devs = [self.device] if self.device else GPS_DEVICES
        for d in devs:
            try:
                self._ser = serial.Serial(d, self.baud, timeout=1)
                print("GPS opened", d)
                return True
            except Exception as e:
                print("GPS open failed on", d, e)
        return False

    def run(self):
        if not self.open_port():
            return
        self.running = True
        while self.running:
            try:
                line = self._ser.readline().decode('ascii', errors='ignore').strip()
                if not line:
                    continue
                if not line.startswith('$'):
                    continue
                msg = pynmea2.parse(line)
                if hasattr(msg, 'latitude') and hasattr(msg, 'longitude'):
                    if msg.latitude and msg.longitude:
                        self.latest['lat'] = msg.latitude
                        self.latest['lon'] = msg.longitude
                        self.latest['ts'] = time.time()
                if msg.sentence_type == 'RMC':
                    try:
                        spd_kn = float(msg.spd_over_grnd or 0.0)
                        self.latest['speed_mps'] = spd_kn * 0.514444
                        if msg.true_course:
                            self.latest['track'] = float(msg.true_course)
                    except Exception:
                        pass
            except Exception as e:
                print('GPS parse error', e)
                time.sleep(0.5)

    def stop(self):
        self.running = False
        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass


if __name__ == '__main__':
    g = GPSReader()
    g.start()
    import time
    for i in range(20):
        print(g.latest)
        time.sleep(1)
