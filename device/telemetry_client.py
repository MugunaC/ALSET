# device/telemetry_client.py
"""Queue telemetry and POST to IVY /api/input
"""
import threading
import queue
import requests
import os
import time

API_URL = os.environ.get('TELEMETRY_URL', os.environ.get('API_URL', 'http://127.0.0.1:3100') + '/api/input')
SEND_INTERVAL = float(os.environ.get('TELEMETRY_INTERVAL', 1.0))

class TelemetryClient:
    def __init__(self, url=API_URL):
        self.url = url
        self.q = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.running = False

    def start(self):
        self.running = True
        self.thread.start()

    def send_now(self, obj):
        self.q.put(obj)

    def _run(self):
        while self.running:
            try:
                obj = self.q.get(timeout=SEND_INTERVAL)
            except Exception:
                continue
            try:
                r = requests.post(self.url, json=obj, timeout=5)
                if r.status_code not in (200,201):
                    print('telemetry post failed', r.status_code, r.text)
            except Exception as e:
                print('telemetry send error', e)

    def stop(self):
        self.running = False


if __name__ == '__main__':
    tc = TelemetryClient()
    tc.start()
    for i in range(5):
        tc.send_now({'ts': int(time.time()*1000), 'payload': {'buttons': [], 'axes': []}})
        time.sleep(1)
