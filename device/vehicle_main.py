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
from device.picam_track import PicamTrack, register_frame_consumer, unregister_frame_consumer
from device.signal_publisher import SignalPublisher
from device.vehicle_ws import DeviceClient
from device.mission_executor import MissionExecutor

# Integration imports for new features
from device.nn_inference import NNInferenceService
from device.dataset_ringbuffer import DatasetRingBuffer
from device.subsumption import Subsumption


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

        # Subsumption manager for arbitrating action proposals
        self.subsumption = Subsumption()

        # dataset capture (100MB cap)
        dataset_dir = os.environ.get('DATASET_CAPTURE_DIR', 'device/captured_dataset')
        self.dataset_capture = DatasetRingBuffer(dataset_dir, max_bytes=100 * 1024 * 1024)
        self.capture_enabled = False

        # NN inference (if model present)
        model_path = os.environ.get('NN_MODEL_PATH', '/opt/alset/models/mobilenet_v2_quantized.onnx')
        self.nn_service = None
        if os.path.exists(model_path):
            def nn_action_cb(action, meta):
                # place proposal into subsumption under 'nn'
                try:
                    self.subsumption.request_action('nn', action, score=action.get('score', 1.0))
                except Exception:
                    pass
            try:
                self.nn_service = NNInferenceService(model_path, action_cb=nn_action_cb, input_size=(224,224))
                # register the NN as a consumer of frames
                register_frame_consumer(self.nn_service.enqueue_frame)
            except Exception:
                import traceback; traceback.print_exc()
                self.nn_service = None

        # capture consumer: saves small JPEGs to the ring buffer when capture_enabled is True
        def _capture_consumer(frame, meta):
            if not self.capture_enabled:
                return
            try:
                from io import BytesIO
                from PIL import Image
                # frame is a BGR numpy array; convert to PIL RGB
                img = Image.fromarray(frame[..., ::-1])
                # downscale for compact storage
                img = img.resize((224,224))
                buf = BytesIO()
                img.save(buf, format='JPEG', quality=75)
                jpeg_bytes = buf.getvalue()
                self.dataset_capture.add_image(jpeg_bytes, meta={'mode': 'capture'})
            except Exception:
                import traceback; traceback.print_exc()

        register_frame_consumer(_capture_consumer)
        self._capture_consumer_fn = _capture_consumer

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

    # configuration helpers for menu wiring
    def set_dataset_capture(self, enabled: bool):
        self.capture_enabled = bool(enabled)

    def set_nn_enabled(self, enabled: bool):
        # placeholder hook: to gracefully enable/disable NN we could add an API to NNInferenceService
        # For now, existence of model controls whether NN runs; toggling can be implemented as needed.
        if self.nn_service is None:
            return
        # If you need runtime enable/disable without discarding the instance, implement a boolean flag in NNInferenceService.
        # Here we'll leave as a no-op.
        pass

    def _shutdown_integration(self):
        # cleanup consumers and services before shutdown
        try:
            unregister_frame_consumer(self._capture_consumer_fn)
        except Exception:
            pass
        if self.nn_service:
            try:
                unregister_frame_consumer(self.nn_service.enqueue_frame)
            except Exception:
                pass
            try:
                self.nn_service.stop()
            except Exception:
                pass


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
        # attempt to gracefully shutdown integration
        try:
            r._shutdown_integration()
        except Exception:
            pass

if __name__ == '__main__':
    asyncio.run(main())