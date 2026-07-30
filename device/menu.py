*** Begin Patch
*** Update File: device/menu.py
@@
 class Menu:
     def __init__(self):
         self.items = [
@@
             {"id": "camera", "label": "Camera Options", "type": "submenu", "children": ["Res", "FPS", "Record"]},
         ]
+        # add route overlay toggle
+        self.items.append({"id": "route_overlay", "label": "Route Overlay", "type": "toggle", "value": True})
         self.open = False
         self.selected = 0
         self.expanded = False
+        # resume prompt state (set by vehicle_main on boot if persisted mission found)
+        self.resume_prompt = None
+        self.resume_action = None
@@
-    def accept(self):
-        self.expand_or_toggle()
+    def accept(self):
+        # If a resume prompt is active, set the resume action instead of normal accept
+        if getattr(self, 'resume_prompt', None):
+            # selected 0 -> Resume, 1 -> Clear
+            self.resume_action = 'resume' if self.selected == 0 else 'clear'
+            return
+        self.expand_or_toggle()
@@
-    def render_overlay(self, frame, hud_state=None):
+    def render_overlay(self, frame, hud_state=None, robot=None):
         # frame: BGR numpy array
         h, w = frame.shape[:2]
         overlay = frame.copy()
-        if not self.open and not hud_state:
-            return frame
+        if not self.open and not hud_state and not getattr(self, 'resume_prompt', None):
+            return frame
@@
-        if self.open:
+        if self.open:
             box_w, box_h = 320, min(360, 40 * len(self.items) + 20)
             x0, y0 = 20, 60
             cv2.rectangle(overlay, (x0,y0), (x0+box_w, y0+box_h), (0,0,0), -1)
@@
                 cv2.putText(frame, label, (x0+10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
-        return frame
+        # route overlay inset drawing
+        try:
+            show_route = next((it for it in self.items if it.get('id')=='route_overlay'), None)
+            if show_route and show_route.get('value') and robot is not None and hasattr(robot, 'mission_executor'):
+                vs = getattr(robot.mission_executor, 'visual_state', None)
+                if vs:
+                    inset_w = int(os.environ.get('ROUTE_OVERLAY_INSET_W', 320))
+                    inset_h = int(os.environ.get('ROUTE_OVERLAY_INSET_H', 240))
+                    ox = w - inset_w - 10
+                    oy = 10
+                    cv2.rectangle(frame, (ox,oy), (ox+inset_w, oy+inset_h), (20,20,20), -1)
+                    scale = float(os.environ.get('ROUTE_OVERLAY_SCALE_PX_PER_M', 10.0))
+                    cx = ox + inset_w // 2
+                    cy = oy + inset_h - 20  # vehicle at bottom center of inset
+                    pts = []
+                    for (px,py) in vs.get('path_local', []):
+                        pts.append((int(cx + px*scale), int(cy - py*scale)))
+                    if len(pts) >= 2:
+                        for i in range(len(pts)-1):
+                            cv2.line(frame, pts[i], pts[i+1], (0,200,255), 2)
+                    # lookahead
+                    lx, ly = vs.get('lookahead', (0,0))
+                    lx_pix = int(cx + lx*scale)
+                    ly_pix = int(cy - ly*scale)
+                    cv2.circle(frame, (lx_pix, ly_pix), 5, (0,128,255), -1)
+                    # next waypoint marker
+                    if len(pts) > 0:
+                        cv2.circle(frame, pts[0], 4, (0,255,0), -1)
+                    # distance label
+                    dist = vs.get('dist_to_wp', None)
+                    if dist is not None:
+                        cv2.putText(frame, f"{dist:.1f}m", (ox+10, oy+20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
+        except Exception:
+            pass
+
+        # render resume prompt modal if present
+        if getattr(self, 'resume_prompt', None):
+            rp = self.resume_prompt
+            mx, my = w//2 - 160, h//2 - 60
+            cv2.rectangle(frame, (mx,my), (mx+320,my+120), (0,0,0), -1)
+            cv2.putText(frame, 'Persisted mission found', (mx+10, my+30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
+            opt1 = 'Resume'
+            opt2 = 'Clear'
+            color1 = (0,255,0) if self.selected == 0 else (200,200,200)
+            color2 = (0,255,0) if self.selected == 1 else (200,200,200)
+            cv2.putText(frame, opt1, (mx+40, my+80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color1, 2)
+            cv2.putText(frame, opt2, (mx+200, my+80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color2, 2)
+        return frame
*** End Patch
