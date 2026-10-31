import asyncio
import time

from app.models import Decision


class InProcessTokenBucket:
    """In-process token bucket — deliberately NOT atomic (baseline)."""

    def __init__(self) -> None:
        self._buckets: dict[str, dict] = {}

    async def check(
        self, key: str, capacity: int, refill_rate: float
    ) -> Decision:
        now = time.time()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = {"tokens": float(capacity), "last_refill": now}
            self._buckets[key] = bucket

        elapsed = max(0.0, now - bucket["last_refill"])
        tokens = min(float(capacity), bucket["tokens"] + elapsed * refill_rate)

        await asyncio.sleep(0)         # yield → race window

        allowed = tokens >= 1
        if allowed:
            tokens -= 1

        bucket["tokens"] = tokens
        bucket["last_refill"] = now

        remaining = int(tokens)
        reset_at = (
            int(now + (capacity - tokens) / refill_rate) if refill_rate > 0 else int(now + 60)
        )
        return Decision(allowed, remaining, reset_at, capacity)