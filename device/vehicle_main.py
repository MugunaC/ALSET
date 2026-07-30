# device/vehicle_main.py
"""Orchestrator: starts GPS, ESP32 comm, telemetry, device WS and the WebRTC publisher.
Run as: python3 device/vehicle_main.py
"""
import asyncio
import os
import time
import glob
import json
from device.gps_reader import GPSReader
from device.esp32_comm import ESP32Comm
from device.telemetry_client import TelemetryClient
from device.menu import Menu
from device.picam_track import PicamTrack
from device.signal_publisher import SignalPublisher
from device.vehicle_ws import DeviceClient
from device.mission_executor import MissionExecutor

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
        # construct PicamTrack and pass the Robot instance so overlays can access mission visual_state
        self.picam = PicamTrack(self.menu, self.gps, self.get_hud, robot=self)
        self.publisher = SignalPublisher(self.picam)
        # attach mission executor (starts on demand)
        self.mission_executor = MissionExecutor(self, control_hz=20, lookahead_m=float(os.environ.get('LOOKAHEAD_M', 2.0)))

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
    # --- resume-on-boot scan for persisted missions ---
    AUTOSTART = os.environ.get('AUTOSTART_PERSISTED_MISSIONS', '0') == '1'
    missions_dir = os.path.join('device', 'missions')
    if os.path.isdir(missions_dir):
        for p in glob.glob(os.path.join(missions_dir, '*.json')):
            try:
                with open(p, 'r') as f:
                    m = json.load(f)
                rt = m.get('_runtime', {})
                state = rt.get('state')
                if state and state != 'completed':
                    if AUTOSTART:
                        # auto-resume if not estopped
                        if not getattr(r.esp, 'estop_latched', False):
                            r.mission_executor.load_mission(m)
                            r.mission_executor.start_mission()
                            if r.debug:
                                print('Auto-resumed mission', m.get('id'))
                    else:
                        # present resume prompt in overlay menu
                        r.pending_mission_to_resume = m
                        r.menu.resume_prompt = {'mission': m, 'path': p, 'selected': 0}
                    break
            except Exception as e:
                print('Error scanning persisted mission', p, e)

    # background task: watch the menu resume_action and act on Resume/Clear
    async def _menu_resume_monitor(robot):
        while True:
            try:
                mp = getattr(robot.menu, 'resume_prompt', None)
                action = getattr(robot.menu, 'resume_action', None)
                if action and mp:
                    if action == 'resume':
                        robot.mission_executor.load_mission(mp['mission'])
                        robot.mission_executor.start_mission()
                        print('Resumed persisted mission', mp['mission'].get('id'))
                    elif action == 'clear':
                        try:
                            os.remove(mp['path'])
                            print('Cleared persisted mission file', mp['path'])
                        except Exception as e:
                            print('Failed to clear persisted mission file', e)
                    robot.menu.resume_prompt = None
                    robot.menu.resume_action = None
                await asyncio.sleep(0.5)
            except Exception:
                await asyncio.sleep(0.5)

    # start monitor
    asyncio.create_task(_menu_resume_monitor(r))

    device_client = DeviceClient(r)
    # run device WS and keep loop for signal publisher
    ws_task = asyncio.create_task(device_client.run())
    try:
        await ws_task
    except asyncio.CancelledError:
        device_client.stop()

if __name__ == '__main__':
    asyncio.run(main())
