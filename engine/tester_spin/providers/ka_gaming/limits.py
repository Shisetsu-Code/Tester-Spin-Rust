"""Shared KA request budget for all sessions in this process."""
import math
import threading
import time
from collections import deque


class RequestGate:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.starts = deque()
        self.lock = threading.Lock()
        self.min_interval_s = 0.0
        self.last_start = None

    def configure_delay(self, seconds):
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("El delay entre operaciones debe ser finito y mayor o igual a cero")
        with self.lock:
            self.min_interval_s = seconds

    def acquire(self, stop_event):
        while True:
            if stop_event.is_set():
                raise InterruptedError("KA Gaming: ejecución detenida")
            with self.lock:
                now = self.clock()
                while self.starts and now - self.starts[0] >= 1.0:
                    self.starts.popleft()
                spacing = 0 if self.last_start is None else self.last_start + self.min_interval_s - now
                rate_wait = 0 if len(self.starts) < 30 else self.starts[0] + 1.0 - now
                delay = max(spacing, rate_wait)
                if delay <= 0:
                    self.starts.append(now)
                    self.last_start = now
                    return
                delay = max(0.000001, delay)
            if stop_event.wait(delay):
                raise InterruptedError("KA Gaming: ejecución detenida")


REQUEST_GATE = RequestGate()
