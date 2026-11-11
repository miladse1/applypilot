"""In-memory sliding-window rate limits.

ApplyPilot runs as one process on the user's own computer, so memory is the right store: no
extra service, and limits reset on restart. A multi-process deployment would need a shared
store such as Redis instead.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: float) -> bool:
        """Record one event for `key`. Returns False (and records nothing) when over the limit."""
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    def count(self, key: str, window_seconds: float) -> int:
        now = time.monotonic()
        with self._lock:
            return sum(1 for moment in self._events.get(key, ()) if moment > now - window_seconds)

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


limiter = SlidingWindowLimiter()


def reset() -> None:
    """Forget every recorded event (tests)."""
    limiter.clear()
