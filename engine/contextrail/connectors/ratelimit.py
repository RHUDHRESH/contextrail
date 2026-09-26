"""An async token bucket for account-wide API rate limits (checklist T123, CLAUDE.md §12).

Freshservice limits calls per minute across the whole account (100-500/min by plan). The bucket refills at
`rate_per_min / 60` tokens per second and holds at most `burst` tokens. In any 60-second window it admits at
most `rate_per_min + burst` calls, so the default (80/min, burst 20) stays within the smallest plan's 100/min
even while other integrations share the account.

Callers are served one at a time under a lock, so concurrent stages share one budget instead of each assuming
the whole of it. The clock and sleep are injectable so tests simulate time instead of waiting.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

_EPSILON = 1e-9  # float round-off after a sleep must not cost a second, tiny sleep


class TokenBucket:
    def __init__(self, rate_per_min: int, *, burst: int | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        if rate_per_min <= 0:
            raise ValueError(f"rate_per_min must be positive, got {rate_per_min}")
        self.rate_per_min = rate_per_min
        self.burst = max(1, rate_per_min // 4) if burst is None else burst
        if self.burst < 1:
            raise ValueError(f"burst must be at least 1, got {burst}")
        self._per_second = rate_per_min / 60.0
        self._clock, self._sleep = clock, sleep
        self._tokens = float(self.burst)
        self._stamp = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(float(self.burst), self._tokens + (now - self._stamp) * self._per_second)
        self._stamp = now

    async def acquire(self) -> None:
        """Wait until one call is allowed, then take it."""
        async with self._lock:
            self._refill()
            while self._tokens < 1.0 - _EPSILON:
                await self._sleep((1.0 - self._tokens) / self._per_second)
                self._refill()
            self._tokens -= 1.0
