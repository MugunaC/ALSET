# device/mission_executor.py
"""Mission executor: loads missions, persists them, and runs the control loop.
Supports real execution using robot.gps and robot.esp and a simple pure-pursuit-like controller.
Adds visual_state for overlay and periodic persistence for resume-on-boot.
"""
import os
import json
import math
import time
import threading
from typing import Dict, Any

MISSIONS_DIR = os.environ.get('MISSIONS_DIR', 'device/missions')
if not os.path.exists(MISSIONS_DIR):
    os.makedirs(MISSIONS_DIR, exist_ok=True)

R_EARTH = 6371000.0  # meters

# helper: convert lat/lon differences to local meters using equirectangular approx
def latlon_to_local_m(lat1, lon1, lat2, lon2):
    # returns dx (east), dy (north) in meters from p1 -> p2
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    lon1r = math.radians(lon1)
    lon2r = math.radians(lon2)
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    mean_lat = (lat1r + lat2r) / 2.0
    dx = dlon * math.cos(mean_lat) * R_EARTH
    dy = dlat * R_EARTH
    return dx, dy


def angle_normalize(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


# simple mapping from curvature to steering [-1..1]
def curvature_to_steer(curvature, max_curv=1.0):
    # clamp and normalize
    c = max(-max_curv, min(max_curv, curvature))
    return c / max_curv


class MissionExecutor(threading.Thread):
    def __init__(self, robot, control_hz=20, lookahead_m=2.0):
        super().__init__(daemon=True)
        self.robot = robot
        self.control_hz = control_hz
        self.lookahead_m = float(os.environ.get('LOOKAHEAD_M', lookahead_m))
        self.running = False
        self.mission = None
        self.current_idx = 0
        self.state = 'idle'
        self.gear_multipliers = {
            -1: float(os.environ.get('GEAR_REVERSE_MULT', -0.5)),
            0: 0.0,
            1: float(os.environ.get('GEAR1_MULT', 0.25)),
            2: float(os.environ.get('GEAR2_MULT', 0.5)),
            3: float(os.environ.get('GEAR3_MULT', 0.75)),
            4: float(os.environ.get('GEAR4_MULT', 1.0)),
        }
        self.arrival_radius_m = float(os.environ.get('MISSION_ARRIVAL_RADIUS_M', 2.0))
        self.slow_radius_multiplier = float(os.environ.get('SLOW_RADIUS_MULT', 2.0))
        self.max_throttle = float(os.environ.get('MAX_THROTTLE', 1.0))
        self.kp_speed = float(os.environ.get('KP_SPEED', 0.7))
        self.min_lookahead = float(os.environ.get('MIN_LOOKAHEAD_M', 1.0))
        self.max_lookahead = float(os.environ.get('MAX_LOOKAHEAD_M', 5.0))
        self._stop_event = threading.Event()
        # persistence & visual state
        self.persist_interval = float(os.environ.get('PERSIST_STATE_INTERVAL_S', 2.0))
        self._last_persist = time.time()
        self.visual_state = None

    def persist_mission(self, mission: Dict[str, Any]):
        mid = mission.get('id') or f"mission_{int(time.time())}"
        path = os.path.join(MISSIONS_DIR, f"{mid}.json")
        with open(path, 'w') as f:
            json.dump(mission, f, indent=2)
        return path

    def persist_state(self):
        # write runtime state back to persisted mission file for resume-on-boot
        if not self.mission or not self.mission.get('_persisted_path'):
            return
        try:
            data = dict(self.mission)
            data['_runtime'] = {
                'state': self.state,
                'current_idx': self.current_idx,
                'ts': int(time.time()*1000)
            }
            with open(self.mission['_persisted_path'], 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print('persist_state error', e)

    def load_mission(self, mission: Dict[str, Any]):
        # basic validation
        if not mission or 'waypoints' not in mission or len(mission['waypoints']) == 0:
            raise ValueError('mission must include waypoints')
        # clamp speed
        mission['speedMps'] = float(mission.get('speedMps', 1.0))
        mission['arrivalRadiusM'] = float(mission.get('arrivalRadiusM', self.arrival_radius_m))
        mission['slowRadiusM'] = float(mission.get('slowRadiusM', mission['speedMps'] * self.slow_radius_multiplier))
        # persist
        path = self.persist_mission(mission)
        mission['_persisted_path'] = path
        # if the file contains _runtime, restore current_idx/state
        try:
            with open(path, 'r') as f:
                existing = json.load(f)
                rt = existing.get('_runtime', {})
                if rt:
                    self.current_idx = int(rt.get('current_idx', 0))
                    # if running previously, keep in ready state until operator starts
                    self.state = rt.get('state', 'ready') if rt.get('state') else 'ready'
        except Exception:
            pass
        self.mission = mission
        if not hasattr(self, 'current_idx'):
            self.current_idx = 0
        if self.robot.debug:
            print('Mission loaded and persisted to', path)

    def start_mission(self):
        if not self.mission:
            raise RuntimeError('no mission loaded')
        if self.state in ('running',):
            return
        self.state = 'running'
        if not self.is_alive():
            self.start()

    def pause(self):
        self.state = 'paused'
        self.robot.esp.safe_send(steer=0.0, throttle=0.0)
        self.persist_state()

    def stop(self):
        self.state = 'idle'
        self._stop_event.set()
        self.robot.esp.safe_send(steer=0.0, throttle=0.0)
        self.persist_state()

    def _compute_visual_state(self, lat, lon, dx, dy, lookahead, goal_x, goal_y, dist):
        # build path_local of upcoming waypoints in meters relative to current pos
        path_local = []
        try:
            for i in range(self.current_idx, len(self.mission['waypoints'])):
                wp = self.mission['waypoints'][i]
                wx, wy = latlon_to_local_m(lat, lon, float(wp['lat']), float(wp['lng']))
                path_local.append((wx, wy))
        except Exception:
            path_local = []
        self.visual_state = {
            'path_local': path_local,
            'lookahead': (goal_x, goal_y),
            'next_wp_idx': self.current_idx,
            'dist_to_wp': dist
        }

    def run(self):
        self.running = True
        dt = 1.0 / float(self.control_hz)
        while not self._stop_event.is_set():
            try:
                if self.state != 'running' or not self.mission:
                    time.sleep(0.1)
                    continue
                # fetch GPS
                gps = getattr(self.robot, 'gps', None)
                if gps is None:
                    # no gps; wait
                    if self.robot.debug:
                        print('MissionExecutor: no GPS available')
                    time.sleep(0.2)
                    continue
                lat = gps.latest.get('lat')
                lon = gps.latest.get('lon')
                speed = gps.latest.get('speed_mps') or gps.latest.get('speed', 0.0) or 0.0
                heading_deg = gps.latest.get('track') or 0.0
                if lat is None or lon is None:
                    # no fix
                    self.robot.telemetry.send_now({'ts': int(time.time()*1000), 'note': 'gps_no_fix'})
                    time.sleep(0.2)
                    continue
                wp = self.mission['waypoints'][self.current_idx]
                wplat = float(wp['lat'])
                wplon = float(wp['lng'])
                dx, dy = latlon_to_local_m(lat, lon, wplat, wplon)
                dist = math.hypot(dx, dy)
                # arrival
                arrival_radius = float(self.mission.get('arrivalRadiusM', self.arrival_radius_m))
                if dist <= arrival_radius:
                    # arrived
                    loiter = float(wp.get('loiterSeconds', 0))
                    self.robot.esp.safe_send(steer=0.0, throttle=0.0)
                    # telemetry and overlay
                    self.robot.telemetry.send_now({'ts': int(time.time()*1000), 'vehicleId': getattr(self.robot, 'vehicle_id', None), 'payload': {'event': 'arrived', 'wp_index': self.current_idx}})
                    # persist state
                    self.persist_state()
                    if loiter > 0:
                        t0 = time.time()
                        while time.time() - t0 < loiter and self.state == 'running':
                            time.sleep(0.1)
                    # advance
                    if self.current_idx + 1 < len(self.mission['waypoints']):
                        self.current_idx += 1
                        # persist on advance
                        self.persist_state()
                        continue
                    else:
                        # finished
                        self.state = 'completed'
                        self.robot.telemetry.send_now({'ts': int(time.time()*1000), 'vehicleId': getattr(self.robot, 'vehicle_id', None), 'payload': {'event': 'mission_completed'}})
                        # ensure neutral
                        self.robot.esp.safe_send(steer=0.0, throttle=0.0)
                        # persist final
                        self.persist_state()
                        continue
                # compute lookahead
                lookahead = max(self.min_lookahead, min(self.max_lookahead, self.lookahead_m + 0.5 * speed))
                goal_ratio = min(1.0, lookahead / dist) if dist > 0.01 else 1.0
                goal_x = dx * goal_ratio
                goal_y = dy * goal_ratio
                # heading
                yaw = math.radians(heading_deg)
                angle_to_goal = math.atan2(goal_y, goal_x)
                alpha = angle_normalize(angle_to_goal - yaw)
                curvature = 0.0
                if lookahead > 0:
                    curvature = 2.0 * math.sin(alpha) / lookahead
                steer_norm = curvature_to_steer(curvature, max_curv=1.0)
                # desired speed
                desired_speed = float(self.mission.get('speedMps', 1.0))
                slow_radius = float(self.mission.get('slowRadiusM', desired_speed * self.slow_radius_multiplier))
                if dist < slow_radius and slow_radius > 0:
                    desired_speed = desired_speed * max(0.0, dist / slow_radius)
                # gear multiplier
                gear = getattr(self.robot, 'gear', 0)
                mult = self.gear_multipliers.get(gear, 1.0)
                desired_speed = desired_speed * abs(mult)
                # speed controller
                speed_err = desired_speed - speed
                throttle_cmd = self.kp_speed * speed_err
                # clamp
                throttle_cmd = max(-1.0, min(1.0, throttle_cmd))
                # AI assists: lane correction blending if available
                lane_corr = 0.0
                try:
                    if hasattr(self.robot, 'menu') and self.robot.menu.items[1].get('value', False):
                        # placeholder for lane correction API
                        if hasattr(self.robot, 'ai_lane_correction'):
                            lane_corr = self.robot.ai_lane_correction()
                except Exception:
                    lane_corr = 0.0
                steer_norm = 0.8 * steer_norm + 0.2 * lane_corr
                # compute visual state for overlay
                try:
                    self._compute_visual_state(lat, lon, dx, dy, lookahead, goal_x, goal_y, dist)
                except Exception:
                    self.visual_state = None
                # send safe
                self.robot.esp.safe_send(steer=steer_norm, throttle=throttle_cmd)
                # telemetry
                self.robot.telemetry.send_now({'ts': int(time.time()*1000), 'vehicleId': getattr(self.robot, 'vehicle_id', None), 'payload': {'wp_index': self.current_idx, 'dist_to_wp': dist, 'speed': speed, 'desired_speed': desired_speed}})
                # periodic persistence
                if time.time() - self._last_persist > self.persist_interval:
                    self.persist_state()
                    self._last_persist = time.time()
                # small sleep
                time.sleep(1.0 / float(self.control_hz))
            except Exception as e:
                print('MissionExecutor error', e)
                time.sleep(0.5)
        self.running = False


if __name__ == '__main__':
    print('MissionExecutor module loaded')
