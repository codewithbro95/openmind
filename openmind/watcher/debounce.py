from __future__ import annotations

import threading
import time

from openmind.watcher.events import FileChangeEvent


class EventDebouncer:
    def __init__(self, delay_seconds: float = 2.0):
        self.delay_seconds = delay_seconds
        self._pending: dict[str, tuple[FileChangeEvent, float]] = {}
        self._lock = threading.Lock()

    def push(self, event: FileChangeEvent, now: float | None = None) -> None:
        deadline = (now if now is not None else time.monotonic()) + self.delay_seconds
        with self._lock:
            self._pending[event.path] = (event, deadline)

    def ready(self, now: float | None = None) -> list[FileChangeEvent]:
        current = now if now is not None else time.monotonic()
        with self._lock:
            paths = [path for path, (_, deadline) in self._pending.items() if deadline <= current]
            events = [self._pending.pop(path)[0] for path in paths]
        return events

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)
