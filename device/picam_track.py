# device/picam_track.py
"""
PicamTrack: provides video frames (numpy BGR arrays) to:
 - the SignalPublisher (as VideoFrame objects)
 - registered frame consumers (callbacks) that receive (frame_numpy, meta)

Consumers:
 - register_frame_consumer(fn): fn(frame_numpy, meta) will be called for each overlayed frame
 - unregister_frame_consumer(fn)
"""

import time
import threading
import numpy as np
from av import VideoFrame

# frame consumers registry
_frame_consumers = []

def register_frame_consumer(fn):
    """Register a consumer function(fn(frame_numpy, meta_dict))."""
    _frame_consumers.append(fn)

def unregister_frame_consumer(fn):
    try:
        _frame_consumers.remove(fn)
    except ValueError:
        pass


class PicamTrack:
    """
    Minimal PicamTrack which is used by SignalPublisher.
    This version expects an object self._picam that provides capture_array() returning a BGR numpy image.
    If your project uses a different camera API, keep the consumer calls below in your capture loop.
    """

    def __init__(self, menu, gps_reader, get_hud_state, robot=None, width=1280, height=720, fps=20):
        self.menu = menu
        self.gps = gps_reader
        self.get_hud_state = get_hud_state
        self.robot = robot
        self.width = width
        self.height = height
        self.fps = fps
        self._running = False
        self._picam = None
        self._last_frame_ts = None

        # lazily create camera handle when start() called
        self._capture_thread = None

    def start(self):
        """
        Start the camera capture thread. The capture loop calls menu.render_overlay
        then converts the overlayed frame to VideoFrame for publisher consumption.
        If your existing code uses an async generator, you can adapt the consumer call placement below.
        """
        if self._running:
            return
        # instantiate your actual camera object here (picamera2, cv2, etc.)
        # Example placeholder: expect self._picam.capture_array() to return BGR numpy
        # If you have an existing camera object, assign it to self._picam before calling start().
        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def stop(self):
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=1.0)
            self._capture_thread = None
        # if camera handle exists, close it here (if applicable)
        # Example: if hasattr(self._picam, 'close'): self._picam.close()

    def _capture_loop(self):
        """
        Capture loop that yields frames to local consumers and to a queue that the SignalPublisher expects.
        For ease of integration with existing SignalPublisher, this method creates VideoFrame objects and
        stores a latest_frame for synchronous retrieval via get_latest_videoframe().
        """
        # Placeholder camera setup if none present — try to import cv2 if available
        if self._picam is None:
            try:
                import cv2
                self._picam = cv2.VideoCapture(0)
                # try setting capture properties
                try:
                    self._picam.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    self._picam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    self._picam.set(cv2.CAP_PROP_FPS, self.fps)
                except Exception:
                    pass
            except Exception:
                self._picam = None

        # For VideoFrame consumers, we will keep the latest produced frame
        self._latest_video_frame = None

        # capture interval
        interval = 1.0 / max(1.0, self.fps)
        while self._running:
            try:
                if hasattr(self._picam, 'capture_array'):
                    arr = self._picam.capture_array()
                else:
                    # assume OpenCV VideoCapture
                    ret, frame = self._picam.read()
                    if not ret:
                        time.sleep(interval)
                        continue
                    arr = frame
                # overlay
                hud = self.get_hud_state()
                # menu.render_overlay should accept (arr, hud, robot=...) and return a BGR numpy frame
                try:
                    frame_overlayed = self.menu.render_overlay(arr, hud, robot=self.robot)
                except TypeError:
                    # fallback if render_overlay doesn't accept robot param
                    frame_overlayed = self.menu.render_overlay(arr, hud)

                # notify consumers with a copy (numpy)
                for fn in list(_frame_consumers):
                    try:
                        fn(frame_overlayed.copy(), {'ts': int(time.time() * 1000)})
                    except Exception:
                        import traceback; traceback.print_exc()

                # convert BGR numpy to VideoFrame for publisher/aiortc usage
                new_frame = VideoFrame.from_ndarray(frame_overlayed, format='bgr24')
                new_frame.pts = None
                new_frame.time_base = None
                # keep latest for synchronous reads (if needed by SignalPublisher)
                self._latest_video_frame = new_frame

                # throttle
                time.sleep(interval)
            except Exception:
                import traceback; traceback.print_exc()
                time.sleep(interval)

    def get_latest_videoframe(self):
        """Return latest VideoFrame; may be None initially."""
        return getattr(self, '_latest_video_frame', None)

    # Compatibility helper in case other modules expect an iterator/generator of VideoFrames
    def frames_generator(self):
        """Generator yielding latest frames as they become available. Blocking."""
        while True:
            vf = self.get_latest_videoframe()
            if vf is not None:
                yield vf
            time.sleep(0.01)