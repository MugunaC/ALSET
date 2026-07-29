# device/esp32_comm.py
"""Communicate with ESP32 over serial (default /dev/ttyUSB0) to set PWM for steering and ESC.
Protocol: JSON lines. Example: {"steer": -0.2, "throttle": 0.45}\n
"""
import serial
import threading
import time
import os
import json

SERIAL_PATH = os.environ.get("ESP32_SERIAL", "/dev/ttyUSB0")
BAUD = int(os.environ.get("ESP32_BAUD", 115200))

class ESP32Comm:
    def __init__(self, path=SERIAL_PATH, baud=BAUD, auto_open=True):
        self.path = path
        self.baud = baud
        self.lock = threading.Lock()
        self.ser = None
        if auto_open:
            self.open()

    def open(self):
        try:
            self.ser = serial.Serial(self.path, self.baud, timeout=0.25)
            time.sleep(0.1)
        except Exception as e:
            print("ESP32 serial open error:", e)
            self.ser = None

    def send(self, steer=None, throttle=None):
        if self.ser is None:
            self.open()
            if self.ser is None:
                return False
        obj = {}
        if steer is not None:
            obj["steer"] = float(steer)
        if throttle is not None:
            obj["throttle"] = float(throttle)
        line = json.dumps(obj) + "\n"
        with self.lock:
            try:
                self.ser.write(line.encode('utf-8'))
                return True
            except Exception as e:
                print("ESP32 write error:", e)
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                return False

    def close(self):
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass


if __name__ == '__main__':
    e = ESP32Comm()
    for i in range(5):
        e.send(steer=0.5, throttle=0.2)
        time.sleep(1)
