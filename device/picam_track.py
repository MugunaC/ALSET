# device/picam_track.py
"""aiortc VideoStreamTrack that captures frames from picamera2 and renders overlays via OpenCV.
"""
import asyncio
import os
import time
import numpy as np
from av import VideoFrame

try:
    from picamera2 import Picamera2, Preview
except Exception:
    Picamera2 = None

import cv2

class PicamTrack:
    def __init__(self, menu, gps_reader, get_hud_state, width=1280, height=720, fps=20):
        self.menu = menu
        self.gps = gps_reader
        self.get_hud_state = get_hud_state
        self.width = width
        self.height = height
        self.fps = fps
        self._running = False
        self._picam = None
        self._last_frame_ts = None

    def start_camera(self):
        if Picamera2 is None:
            raise RuntimeError('picamera2 not available on this system')
        self._picam = Picamera2()
        config = self._picam.create_preview_configuration({'size': (self.width, self.height)})
        self._picam.configure(config)
        self._picam.start()
        self._running = True

    async def frames(self):
        # generator yielding VideoFrame
        if self._picam is None:
            self.start_camera()
        while True:
            arr = self._picam.capture_array()
            # overlay
            hud = self.get_hud_state()
            frame = self.menu.render_overlay(arr, hud)
            # convert BGR numpy to VideoFrame
            new_frame = VideoFrame.from_ndarray(frame, format='bgr24')
            new_frame.pts = None
            new_frame.time_base = None
            yield new_frame
            await asyncio.sleep(1.0 / self.fps)

    # convenience for aiortc MediaStreamTrack compatibility
    async def recv(self):
        gen = self.frames().__aiter__()
        return await gen.__anext__()
