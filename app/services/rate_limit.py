"""Sliding-window attempt limits for the public auth endpoints.

Counts live in this process. That fits the single uvicorn worker we run; more
workers or replicas would each count separately and need a shared store.
"""

import math
import time
from collections import deque

# Forget idle keys once this many pile up, so spoofed or rotating keys can't grow memory forever.
SWEEP_THRESHOLD = 10_000


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._attempts: dict[str, deque[float]] = {}

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts.setdefault(key, deque())
        while attempts and attempts[0] <= now - self.window:
            attempts.popleft()
        return attempts

    def retry_after(self, key: str) -> int | None:
        """Seconds until `key` may try again, or None while it is under the limit."""
        now = time.monotonic()
        attempts = self._recent(key, now)
        if len(attempts) < self.limit:
            return None
        return max(1, math.ceil(attempts[0] + self.window - now))

    def record(self, key: str) -> None:
        now = time.monotonic()
        if len(self._attempts) >= SWEEP_THRESHOLD:
            self._sweep(now)
        self._recent(key, now).append(now)

    def hit(self, key: str) -> int | None:
        """Record an attempt unless `key` is over the limit; return the wait if it is."""
        wait = self.retry_after(key)
        if wait is None:
            self.record(key)
        return wait

    def forget(self, key: str) -> None:
        self._attempts.pop(key, None)

    def reset(self) -> None:
        self._attempts.clear()

    def _sweep(self, now: float) -> None:
        for key in list(self._attempts):
            if not self._recent(key, now):
                del self._attempts[key]
