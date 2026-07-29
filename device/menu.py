# device/menu.py
"""Menu state machine and overlay renderer.
"""
import cv2
import numpy as np

class Menu:
    def __init__(self):
        self.items = [
            {"id": "hud", "label": "HUD", "type": "toggle", "value": True},
            {"id": "lane", "label": "Lane Following", "type": "toggle", "value": False},
            {"id": "nav", "label": "Navigation", "type": "toggle", "value": False},
            {"id": "avoid", "label": "Obstacle Avoidance", "type": "toggle", "value": True},
            {"id": "signs", "label": "Traffic Sign ID", "type": "toggle", "value": False},
            {"id": "camera", "label": "Camera Options", "type": "submenu", "children": ["Res", "FPS", "Record"]},
        ]
        self.open = False
        self.selected = 0
        self.expanded = False

    def toggle(self):
        self.open = not self.open

    def move_up(self):
        if not self.open: self.open = True
        self.selected = max(0, self.selected - 1)

    def move_down(self):
        if not self.open: self.open = True
        self.selected = min(len(self.items) - 1, self.selected + 1)

    def expand_or_toggle(self):
        s = self.items[self.selected]
        if s.get('type') == 'toggle':
            s['value'] = not s.get('value', False)
        else:
            self.expanded = not self.expanded

    def collapse(self):
        self.expanded = False

    def accept(self):
        self.expand_or_toggle()

    def cancel(self):
        self.open = False
        self.expanded = False

    def render_overlay(self, frame, hud_state=None):
        # frame: BGR numpy array
        h, w = frame.shape[:2]
        overlay = frame.copy()
        if not self.open and not hud_state:
            return frame
        # HUD top-left
        if hud_state and self.items[0]['value']:
            text = f"G:{hud_state.get('gear')} S:{hud_state.get('speed', 0):.1f}m/s B:{hud_state.get('battery','?')}"
            cv2.putText(overlay, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
        if self.open:
            box_w, box_h = 320, min(360, 40 * len(self.items) + 20)
            x0, y0 = 20, 60
            cv2.rectangle(overlay, (x0,y0), (x0+box_w, y0+box_h), (0,0,0), -1)
            alpha = 0.5
            cv2.addWeighted(overlay, alpha, frame, 1-alpha, 0, frame)
            # draw items
            for i, it in enumerate(self.items):
                y = y0 + 30 + i*40
                color = (0,255,0) if i==self.selected else (200,200,200)
                label = it['label'] + (" [ON]" if it.get('type')=='toggle' and it.get('value') else (" [OFF]" if it.get('type')=='toggle' else ""))
                cv2.putText(frame, label, (x0+10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        return frame
