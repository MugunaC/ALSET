# device/test_mission.py
import time, math, json
from device.mission_executor import MissionExecutor
from types import SimpleNamespace

class MockESP:
    def __init__(self):
        self.last = {}
    def safe_send(self, steer=None, throttle=None):
        self.last = {'steer': steer, 'throttle': throttle}
        print("ESP cmd -> steer:", round(steer if steer is not None else 0,3), "throttle:", round(throttle if throttle is not None else 0,3))

class MockGPS:
    def __init__(self):
        self.latest = {'lat': None, 'lon': None, 'speed_mps': 0.0, 'track': 0.0}
    def set_pos(self, lat, lon, speed=0.0, track=0.0):
        self.latest['lat'] = lat
        self.latest['lon'] = lon
        self.latest['speed_mps'] = speed
        self.latest['track'] = track

class DummyRobot:
    def __init__(self):
        self.esp = MockESP()
        self.gps = MockGPS()
        self.telemetry = SimpleNamespace(send_now=lambda obj: print("TELEMETRY", obj))
        self.menu = SimpleNamespace(items=[{}, {'value': False}])  # placeholder for lane assist slot
        self.vehicle_id = "TEST-VH"
        self.gear = 1
        self.debug = True
    def ai_lane_correction(self):
        return 0.0

# Simulate a straight mission: two waypoints roughly 20 meters apart
mission = {
    "id": "test_mission_1",
    "waypoints": [
        {"lat": 37.4219999, "lng": -122.0840575},
        {"lat": 37.4220999, "lng": -122.0840575}
    ],
    "speedMps": 0.5,
    "arrivalRadiusM": 0.5,
    "slowRadiusM": 3.0
}


def simulate():
    robot = DummyRobot()
    execr = MissionExecutor(robot, control_hz=10, lookahead_m=2.0)
    robot.mission_executor = execr
    execr.load_mission(mission)
    # start mission thread
    execr.start_mission()
    # simulate GPS moving from point a toward b at 0.5 m/s
    lat0 = 37.4219999
    lon0 = -122.0840575
    steps = 60
    for i in range(steps):
        # small increment northwards ~ 0.000001 degree ~ 0.11m at lat 37
        frac = i / steps
        lat = lat0 + frac * 0.0001  # tuned for visible movement
        lon = lon0
        robot.gps.set_pos(lat, lon, speed=0.5, track=0.0)
        time.sleep(0.2)
    # let mission thread finish a bit
    time.sleep(2)
    execr.stop()

if __name__ == '__main__':
    simulate()
