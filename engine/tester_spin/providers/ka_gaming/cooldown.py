"""Explicit server retry deadlines shared by KA sessions and processes."""
import json
import math
import os
import time
import uuid
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit


class ServerRetryAfter(RuntimeError):
    def __init__(self, metadata):
        self.metadata = metadata
        super().__init__("SERVER_RETRY_AFTER: KA HTTP " + str(metadata["http_status"])
            + "; retry_at=" + str(metadata["retry_at"]) + "; no se envían solicitudes durante la pausa del servidor")


@contextmanager
def _file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"0"); handle.flush()
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ServerCooldown:
    def __init__(self, provider_root, *, clock=time.time):
        self.path = Path(provider_root) / "server-cooldown.json"
        self.clock = clock
        self.memory = {}

    def _read(self):
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            deadline = state.get("retry_at")
            status = state.get("http_status")
            if (type(deadline) in (int, float) and math.isfinite(deadline) and deadline >= 0
                    and type(status) is int and 300 <= status <= 599
                    and isinstance(state.get("endpoint"), str)):
                return state
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return {}

    def details(self):
        state = max((self.memory, self._read()), key=lambda item: item.get("retry_at", 0))
        return dict(state) if state.get("retry_at", 0) > self.clock() else {}

    def remaining_s(self):
        return max(0.0, self.details().get("retry_at", 0) - self.clock())

    def check(self, stop_event):
        if stop_event.is_set():
            raise InterruptedError("KA Gaming: ejecución detenida")
        metadata = self.details()
        if metadata:
            raise ServerRetryAfter(metadata)

    def observe(self, status, headers, endpoint):
        if type(status) is not int or not 300 <= status <= 599:
            return
        value = next((value for key, value in headers.items() if str(key).lower() == "retry-after"), None)
        if not isinstance(value, str) or not value.strip():
            return
        now = self.clock()
        try:
            delay = float(value)
            if not math.isfinite(delay) or delay < 0:
                return
            deadline = now + delay
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    return
                deadline = date.timestamp()
            except (ValueError, TypeError, OverflowError):
                return
        if not math.isfinite(deadline) or deadline <= now:
            return
        parsed = urlsplit(endpoint)
        state = {"retry_at": deadline, "http_status": status,
            "endpoint": parsed.scheme + "://" + parsed.netloc + parsed.path,
            "source": "response.Retry-After"}
        self.memory = max((self.memory, state), key=lambda item: item.get("retry_at", 0))
        with _file_lock(self.path.with_suffix(".lock")):
            state = max((self._read(), self.memory), key=lambda item: item.get("retry_at", 0))
            temporary = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_text(json.dumps(state), encoding="utf-8")
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
