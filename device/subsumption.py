# device/subsumption.py
import time
import threading

class Subsumption:
    """
    Minimal subsumption manager: collects action proposals and returns a chosen action.
    Priority: 'safety' > 'operator' > 'mission' > 'nn' > 'automation'
    Each proposal: { 'action': {...}, 'score': float, 'ts': timestamp }
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.requests = {}

    def request_action(self, source, action, score=1.0):
        with self._lock:
            self.requests[source] = {'action': action, 'score': float(score), 'ts': time.time()}

    def clear_source(self, source):
        with self._lock:
            if source in self.requests:
                del self.requests[source]

    def choose(self):
        with self._lock:
            # safety override
            if 'safety' in self.requests:
                return self.requests['safety']['action']
            if 'operator' in self.requests:
                return self.requests['operator']['action']
            if 'mission' in self.requests:
                return self.requests['mission']['action']
            if 'nn' in self.requests:
                return self.requests['nn']['action']
            if 'automation' in self.requests:
                return self.requests['automation']['action']
            return None