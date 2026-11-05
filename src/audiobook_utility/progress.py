"""A single pending main-context update per operation, independent of GTK."""
import threading


class ProgressDispatch:
    def __init__(self, apply, schedule):
        self.apply, self.schedule = apply, schedule
        self._lock = threading.Lock()
        self._pending = False
        self._closed = False
        self._latest = None

    def __call__(self, fraction, text):
        with self._lock:
            if self._closed:
                return
            self._latest = (max(0, min(1, fraction)), text)
            if self._pending:
                return
            self._pending = True
        self.schedule(self._deliver)

    def _deliver(self):
        with self._lock:
            self._pending = False
            value, self._latest = self._latest, None
            if self._closed:
                return False
        if value is not None:
            self.apply(*value)
        return False

    def close(self):
        with self._lock:
            self._closed, self._latest = True, None
