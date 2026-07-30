*** Begin Patch
*** Update File: device/picam_track.py
@@
-class PicamTrack:
-    def __init__(self, menu, gps_reader, get_hud_state, width=1280, height=720, fps=20):
-        self.menu = menu
-        self.gps = gps_reader
-        self.get_hud_state = get_hud_state
+class PicamTrack:
+    def __init__(self, menu, gps_reader, get_hud_state, robot=None, width=1280, height=720, fps=20):
+        self.menu = menu
+        self.gps = gps_reader
+        self.get_hud_state = get_hud_state
+        self.robot = robot
         self.width = width
         self.height = height
         self.fps = fps
         self._running = False
         self._picam = None
         self._last_frame_ts = None
@@
-            arr = self._picam.capture_array()
-            # overlay
-            hud = self.get_hud_state()
-            frame = self.menu.render_overlay(arr, hud)
+            arr = self._picam.capture_array()
+            # overlay
+            hud = self.get_hud_state()
+            frame = self.menu.render_overlay(arr, hud, robot=self.robot)
             # convert BGR numpy to VideoFrame
             new_frame = VideoFrame.from_ndarray(frame, format='bgr24')
             new_frame.pts = None
             new_frame.time_base = None
             yield new_frame
*** End Patch
