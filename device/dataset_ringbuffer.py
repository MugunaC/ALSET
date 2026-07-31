# device/dataset_ringbuffer.py
import os
import time
import json
import threading
from pathlib import Path

class DatasetRingBuffer:
    def __init__(self, directory, max_bytes=100 * 1024 * 1024):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = int(max_bytes)
        self._lock = threading.Lock()
        self._index = []
        self._rebuild_index()

    def _rebuild_index(self):
        files = sorted(self.dir.glob('*.jpg'), key=lambda p: p.stat().st_mtime)
        self._index = [(p, p.stat().st_size, p.stat().st_mtime) for p in files]

    def _current_size(self):
        return sum(s for _, s, _ in self._index)

    def _evict_if_needed(self, needed_bytes):
        with self._lock:
            cur = self._current_size()
            if cur + needed_bytes <= self.max_bytes:
                return
            self._index.sort(key=lambda t: t[2])
            while self._index and (cur + needed_bytes > self.max_bytes):
                p, s, _ = self._index.pop(0)
                try:
                    p.unlink()
                    cur -= s
                    # also remove corresponding .json if exists
                    meta = p.with_suffix('.json')
                    if meta.exists():
                        try: meta.unlink()
                        except: pass
                except FileNotFoundError:
                    pass

    def add_image(self, image_bytes, meta=None):
        timestamp = int(time.time() * 1000)
        fname = f"{timestamp}.jpg"
        meta_fname = f"{timestamp}.json"
        filepath = self.dir / fname
        meta_path = self.dir / meta_fname
        size = len(image_bytes)
        with self._lock:
            self._evict_if_needed(size)
            with open(filepath, 'wb') as f:
                f.write(image_bytes)
            if meta is None:
                meta = {}
            meta.update({'ts': timestamp})
            with open(meta_path, 'w') as mf:
                json.dump(meta, mf)
            self._index.append((filepath, size, timestamp))
        return str(filepath)

    def list_files(self):
        with self._lock:
            return [str(p) for (p, _, _) in self._index]