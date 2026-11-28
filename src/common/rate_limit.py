"""Thread-safe in-memory sliding-window rate limiter for API abuse & brute-force protection."""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowRateLimiter:
    """In-memory per-(bucket, key) sliding-window rate limiter with bounded key eviction."""

    def __init__(self, *, max_keys: int = 8192) -> None:
        self._max_keys = max(128, int(max_keys))
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str], deque[float]] = {}

    def allow(
        self,
        bucket: str,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> tuple[bool, int]:
        """Record an event if under limit and return (allowed, retry_after_seconds)."""
        if limit <= 0 or window_seconds <= 0:
            return True, 0

        ts = time.monotonic() if now is None else float(now)
        cutoff = ts - window_seconds
        full_key = (bucket, key)

        with self._lock:
            dq = self._events.get(full_key)
            if dq is None:
                if len(self._events) >= self._max_keys:
                    self._prune_locked(cutoff)
                    if len(self._events) >= self._max_keys:
                        oldest_key = next(iter(self._events))
                        self._events.pop(oldest_key, None)
                dq = deque()
                self._events[full_key] = dq

            while dq and dq[0] <= cutoff:
                dq.popleft()

            if len(dq) >= limit:
                retry_after = max(1, int((dq[0] + window_seconds) - ts) + 1)
                return False, retry_after

            dq.append(ts)
            return True, 0

    def is_limited(
        self,
        bucket: str,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> tuple[bool, int]:
        """Check whether (bucket, key) is currently at/over limit without recording a hit."""
        if limit <= 0 or window_seconds <= 0:
            return False, 0

        ts = time.monotonic() if now is None else float(now)
        cutoff = ts - window_seconds
        full_key = (bucket, key)

        with self._lock:
            dq = self._events.get(full_key)
            if not dq:
                return False, 0
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if not dq:
                self._events.pop(full_key, None)
                return False, 0
            if len(dq) >= limit:
                retry_after = max(1, int((dq[0] + window_seconds) - ts) + 1)
                return True, retry_after
            return False, 0

    def _prune_locked(self, default_cutoff: float) -> None:
        empty_keys = [
            k
            for k, dq in self._events.items()
            if not dq or dq[-1] <= default_cutoff
        ]
        for k in empty_keys:
            self._events.pop(k, None)
