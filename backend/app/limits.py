"""Rate limits and usage caps, kept in memory per process."""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], float]


class SlidingWindowLimiter:
    """Allow at most `limit` events per key within `window` seconds. A limit of 0 disables it."""

    def __init__(self, limit: int, window: float, clock: Clock = time.time) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """True if allowed under the limit (does not record a hit)."""
        if self.limit <= 0:
            return True
        with self._lock:
            return len(self._prune(key)) < self.limit

    def hit(self, key: str) -> bool:
        """Record a hit if allowed. Returns False when the limit is reached."""
        if self.limit <= 0:
            return True
        with self._lock:
            hits = self._prune(key)
            if len(hits) >= self.limit:
                return False
            hits.append(self.clock())
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            hits = self._prune(key)
            if not hits:
                return 0
            return max(1, int(hits[0] + self.window - self.clock()) + 1)

    def _prune(self, key: str) -> deque[float]:
        hits = self._hits[key]
        cutoff = self.clock() - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits


class DailyCap:
    """At most `limit` uses per UTC day across all users. A limit of 0 disables it."""

    def __init__(self, limit: int, clock: Clock = time.time) -> None:
        self.limit = limit
        self.clock = clock
        self._day = ""
        self._count = 0
        self._lock = threading.Lock()

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).strftime("%Y-%m-%d")

    def check(self) -> bool:
        if self.limit <= 0:
            return True
        with self._lock:
            self._roll()
            return self._count < self.limit

    def take(self) -> bool:
        if self.limit <= 0:
            return True
        with self._lock:
            self._roll()
            if self._count >= self.limit:
                return False
            self._count += 1
            return True

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self._count = today, 0


class LiveQuota:
    """Decides whether a document may use the paid provider, or should use demo mode."""

    def __init__(self, per_ip_per_hour: int, per_day: int, clock: Clock = time.time) -> None:
        self.per_ip = SlidingWindowLimiter(per_ip_per_hour, 3600, clock)
        self.daily = DailyCap(per_day, clock)

    def take(self, ip: str) -> str | None:
        """Consume one live extraction. Returns None if allowed, else a reason for the notice."""
        if not self.per_ip.check(ip):
            return (
                "You've reached the hourly limit for live extractions, so this one used demo mode."
            )
        if not self.daily.take():
            return (
                "The demo's daily limit for live extractions is used up, "
                "so this one used demo mode."
            )
        self.per_ip.hit(ip)
        return None
