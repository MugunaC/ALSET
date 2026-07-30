*** Begin Patch
*** Update File: device/mission_executor.py
@@
     def persist_mission(self, mission: Dict[str, Any]):
         mid = mission.get('id') or f"mission_{int(time.time())}"
         path = os.path.join(MISSIONS_DIR, f"{mid}.json")
         with open(path, 'w') as f:
             json.dump(mission, f, indent=2)
         return path
+
+    def persist_state(self):
+        # write runtime state back to persisted mission file for resume-on-boot
+        if not self.mission or not self.mission.get('_persisted_path'):
+            return
+        try:
+            data = dict(self.mission)
+            data['_runtime'] = {
+                'state': self.state,
+                'current_idx': self.current_idx,
+                'ts': int(time.time()*1000)
+            }
+            with open(self.mission['_persisted_path'], 'w') as f:
+                json.dump(data, f, indent=2)
+        except Exception as e:
+            print('persist_state error', e)
*** End Patch
