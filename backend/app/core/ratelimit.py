"""In-process sliding-window rate limiter for expensive operations."""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    # shortcut: per-process memory; with several API replicas, move this to Redis or a DB table.
    def __init__(self) -> None:
        self._hits: dict[tuple, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: tuple, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
