import asyncio
import time
from collections import defaultdict

from app.models import Decision


class InProcessFixedWindow:
    """In-process fixed window — deliberately NOT atomic.

    Used as a baseline to measure what Redis+Lua buys us, and to demonstrate
    the race condition that motivates the distributed design.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)
        self._windows: dict[str, int] = {}

    async def check(self, key: str, capacity: int, window_seconds: int) -> Decision:
        now = int(time.time())
        window_id = now // window_seconds

        if self._windows.get(key) != window_id:
            self._windows[key] = window_id
            self._counts[key] = 0

        current = self._counts.get(key, 0)
        await asyncio.sleep(0)         # yield → creates the race window
        current += 1
        self._counts[key] = current

        allowed   = current <= capacity
        remaining = max(0, capacity - current)
        reset_at  = (window_id + 1) * window_seconds
        return Decision(allowed, remaining, reset_at, capacity)