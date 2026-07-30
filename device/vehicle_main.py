*** Begin Patch
*** Update File: device/vehicle_main.py
@@
 from device.vehicle_ws import DeviceClient
+from device.mission_executor import MissionExecutor
@@
     def __init__(self):
@@
         self.picam = PicamTrack(self.menu, self.gps, self.get_hud)
         self.publisher = SignalPublisher(self.picam)
+        # attach mission executor (starts on demand)
+        self.mission_executor = MissionExecutor(self, control_hz=20, lookahead_m=float(os.environ.get('LOOKAHEAD_M', 2.0)))
*** End Patch
