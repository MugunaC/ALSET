# device/vehicle_main.py
"""Orchestrator: starts GPS, ESP32 comm, telemetry, device WS and the WebRTC publisher.
Run as: python3 device/vehicle_main.py
"""
import asyncio
import os
import time
from device.gps_reader import GPSReader
from device.esp32_comm import ESP32Comm
from device.telemetry_client import TelemetryClient
from device.menu import Menu
from device.picam_track import PicamTrack
from device.signal_publisher import SignalPublisher
from device.vehicle_ws import DeviceClient

class Robot:
    def __init__(self):
        self.debug = bool(os.environ.get('DEBUG', False))
        self.menu = Menu()
        self.gps = GPSReader()
        self.esp = ESP32Comm()
        self.telemetry = TelemetryClient()
        self.gear = 0

        def get_hud():
            return {
                'gear': self.gear,
                'speed': self.gps.latest.get('speed_mps', 0) if self.gps.latest.get('speed_mps') else 0.0,
                'battery': 'unknown',
            }
        self.get_hud = get_hud
        self.picam = PicamTrack(self.menu, self.gps, self.get_hud)
        self.publisher = SignalPublisher(self.picam)

    def start(self):
        # start background components
        self.gps.start()
        self.telemetry.start()

    def set_steering(self, v):
        # v in [-1..1]
        self.esp.send(steer=v)

    def set_throttle_and_brake(self, throttle, brake):
        # throttle/brake 0..1 -> compute signed throttle
        effective = max(-1.0, min(1.0, throttle - brake))
        self.esp.send(throttle=effective)
        # send telemetry
        self.telemetry.send_now({
            'ts': int(time.time()*1000),
            'vehicleId': os.environ.get('VEHICLE_ID', 'VH-001'),
            'payload': {'buttons': [], 'axes': [], 'vehicleId': os.environ.get('VEHICLE_ID')},
            'bytes': 0
        })

    def gear_up(self):
        if self.gear < 4:
            self.gear += 1
    def gear_down(self):
        if self.gear > -1:
            self.gear -= 1
    def set_neutral(self):
        self.gear = 0

async def main():
    r = Robot()
    r.start()
    device_client = DeviceClient(r)
    # run device WS and keep loop for signal publisher
    ws_task = asyncio.create_task(device_client.run())
    try:
        await ws_task
    except asyncio.CancelledError:
        device_client.stop()

if __name__ == '__main__':
    asyncio.run(main())
