# device/vehicle_ws.py
"""IVY device WebSocket client — authenticates as device, receives control messages and dispatches to robot components.
"""
import asyncio
import json
import os
import time
import secrets
import hmac
import hashlib
import websockets

DEVICE_SECRET = os.environ.get("DEVICE_SHARED_SECRET", "ivy-dev-device-secret")
VEHICLE_ID = os.environ.get("VEHICLE_ID", "VH-001")
DEVICE_ID = os.environ.get("DEVICE_ID", "PICO-VH-001")
DEVICE_WS = os.environ.get("DEVICE_WS", "ws://127.0.0.1:4000")
PROTOCOL_VERSION = 1

# controller mapping (as provided)
BUTTONS = {
    "X": 0,
    "O": 1,
    "SQUARE": 2,
    "TRI": 3,
    "L1": 4,
    "R1": 5,
    "L2": 6,
    "R2": 7,
    "SHARE": 8,
    "OPTIONS": 9,
    "L3": 10,
    "R3": 11,
    "DPAD_UP": 12,
    "DPAD_DOWN": 13,
    "DPAD_LEFT": 14,
    "DPAD_RIGHT": 15,
}

AXES = {
    "LEFT_X": 0,
    "LEFT_Y": 1,
    "RIGHT_X": 2,
    "RIGHT_Y": 3,
}


def make_sig(vehicle_id, device_id, ts=None, nonce=None, secret=DEVICE_SECRET):
    ts = int(ts or time.time() * 1000)
    nonce = nonce or f"{secrets.token_hex(8)}"
    msg = f"{vehicle_id}|{device_id}|{ts}|{nonce}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return ts, nonce, sig


class DeviceClient:
    def __init__(self, robot):
        self.robot = robot
        self.url = os.environ.get("DEVICE_WS", DEVICE_WS)
        self.backoff = 1
        self.running = False
        self.last_control_ts = None

    async def send_device_hello(self, ws):
        ts, nonce, sig = make_sig(VEHICLE_ID, DEVICE_ID)
        msg = {
            "type": "device_hello",
            "protocolVersion": PROTOCOL_VERSION,
            "payload": {
                "vehicleId": VEHICLE_ID,
                "deviceId": DEVICE_ID,
                "ts": ts,
                "nonce": nonce,
                "sig": sig,
                "fw": os.environ.get("DEVICE_FW", "alset-pi-0.1"),
                "caps": ["control", "location", "camera_status", "publisher"]
            },
        }
        await ws.send(json.dumps(msg))

    async def handle_control(self, payload):
        # map IVY control payload to robot
        self.last_control_ts = int(time.time() * 1000)
        axes = payload.get("payload", {}).get("payload", payload.get("payload")) if isinstance(payload.get("payload"), dict) else payload.get("payload", {})
        # robust extraction for either nested or flat payload
        if isinstance(axes, dict):
            buttons = axes.get("buttons", [])
            axis_vals = axes.get("axes", [])
        else:
            buttons = payload.get("payload", {}).get("buttons", [])
            axis_vals = payload.get("payload", {}).get("axes", [])
        # debug
        if self.robot.debug:
            print("control payload -> axes", axis_vals, "buttons", buttons)

        # steering from left stick horizontal
        steer = 0.0
        if len(axis_vals) > AXES["LEFT_X"]:
            steer = float(axis_vals[AXES["LEFT_X"]])
        # send steering via robot API (which may perform safe_send internally)
        self.robot.set_steering(steer)

        # throttle and brake from triggers (R2 index 7, L2 index 6)
        r2 = float(buttons[BUTTONS["R2"]]) if len(buttons) > BUTTONS["R2"] else (axis_vals[AXES.get("RIGHT_Y", 3)] if len(axis_vals) > 3 else 0.0)
        l2 = float(buttons[BUTTONS["L2"]]) if len(buttons) > BUTTONS["L2"] else (axis_vals[AXES.get("LEFT_Y", 1)] if len(axis_vals) > 1 else 0.0)
        # normalize triggers: some controllers send 0..1 on triggers, others -1..1
        def normalize_trigger(v):
            try:
                v = float(v)
            except Exception:
                return 0.0
            if v >= -1.0 and v <= 1.0:
                # if in -1..1, map so that rest is -1 => 0; 1 => 1
                return max(0.0, (v + 1.0) / 2.0)
            return v
        r2n = normalize_trigger(r2)
        l2n = normalize_trigger(l2)
        self.robot.set_throttle_and_brake(r2n, l2n)

        # gear buttons
        r1 = (len(buttons) > BUTTONS["R1"] and buttons[BUTTONS["R1"]])
        l1 = (len(buttons) > BUTTONS["L1"] and buttons[BUTTONS["L1"]])
        if r1 and l1:
            self.robot.set_neutral()
        elif r1:
            self.robot.gear_up()
        elif l1:
            self.robot.gear_down()

        # DPAD navigation
        d_up = (len(buttons) > BUTTONS["DPAD_UP"] and buttons[BUTTONS["DPAD_UP"]])
        d_down = (len(buttons) > BUTTONS["DPAD_DOWN"] and buttons[BUTTONS["DPAD_DOWN"]])
        d_left = (len(buttons) > BUTTONS["DPAD_LEFT"] and buttons[BUTTONS["DPAD_LEFT"]])
        d_right = (len(buttons) > BUTTONS["DPAD_RIGHT"] and buttons[BUTTONS["DPAD_RIGHT"]])
        if d_up:
            self.robot.menu.move_up()
        if d_down:
            self.robot.menu.move_down()
        if d_right:
            self.robot.menu.expand_or_toggle()
        if d_left:
            self.robot.menu.collapse()

        # accept / cancel
        if len(buttons) > BUTTONS["X"] and buttons[BUTTONS["X"]]:
            self.robot.menu.accept()
        if len(buttons) > BUTTONS["O"] and buttons[BUTTONS["O"]]:
            self.robot.menu.cancel()

    async def run(self):
        self.running = True
        while self.running:
            try:
                async with websockets.connect(self.url) as ws:
                    await self.send_device_hello(ws)
                    self.backoff = 1
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except Exception:
                            continue
                        t = data.get("type")
                        if t == "control":
                            await self.handle_control(data)
                        elif t == "mission":
                            # mission message handling: load, persist, and start mission
                            try:
                                payload = data.get("payload") or data
                                if not hasattr(self.robot, "mission_executor"):
                                    from device.mission_executor import MissionExecutor
                                    self.robot.mission_executor = MissionExecutor(self.robot)
                                self.robot.mission_executor.load_mission(payload)
                                # do not automatically start if mission indicates autostart==false; default start
                                autostart = payload.get('autostart', True)
                                if autostart:
                                    self.robot.mission_executor.start_mission()
                                # ack back to server
                                await ws.send(json.dumps({"type": "mission_ack", "status": "accepted", "missionId": payload.get("id", None)}))
                                if self.robot.debug:
                                    print("Mission accepted:", payload.get("id"))
                            except Exception as e:
                                try:
                                    await ws.send(json.dumps({"type": "mission_ack", "status": "error", "error": str(e)}))
                                except Exception:
                                    pass
                                if self.robot.debug:
                                    import traceback
                                    print("Mission handling error:", traceback.format_exc())
                        elif t == "ping":
                            await ws.send(json.dumps({"type": "pong", "ts": int(time.time() * 1000)}))
                        elif t == "auth_ok":
                            print("device auth ok")
                        elif t == "auth_error":
                            print("device auth error", data.get("message"))
                        # other server messages logged
                        if self.robot.debug:
                            print("WS_MESSAGE", data)
            except Exception as e:
                print("Device WS error:", e)
                await asyncio.sleep(self.backoff)
                self.backoff = min(self.backoff * 2, 60)

    def stop(self):
        self.running = False


# For manual test
if __name__ == "__main__":
    import argparse
    from menu import Menu

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEVICE_WS)
    args = parser.parse_args()
    class DummyRobot:
        def __init__(self):
            self.debug = True
            self.menu = Menu()
        def set_steering(self, v): print("steer", v)
        def set_throttle_and_brake(self, t, b): print("throttle", t, "brake", b)
        def gear_up(self): print("gear up")
        def gear_down(self): print("gear down")
        def set_neutral(self): print("neutral")
    rc = DeviceClient(DummyRobot())
    asyncio.run(rc.run())
