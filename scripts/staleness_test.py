"""
Prove (or disprove) the "no stale rules" claim.

  1. Read the current X-RateLimit-Limit for demo-key.
  2. UPDATE the capacity in Postgres.
  3. Immediately fire 200 requests and count how many still see the old
     capacity in their response headers.
  4. Restore the original capacity.

Expected output: "0/200 stale" — meaning the new rule took effect on the
first request after the update.

Usage:
    python scripts/staleness_test.py
"""
import asyncio
import os
import time

import asyncpg
import httpx

API_KEY = "demo-key"
NEW_CAPACITY = 3
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
APP_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/traffic",
)
ASYNC_PG_DSN = APP_DSN.replace("+asyncpg", "")


async def _get_limit(client: httpx.AsyncClient) -> int:
    r = await client.get("/api/data", headers={"X-API-Key": API_KEY})
    return int(r.headers["x-ratelimit-limit"])


async def _set_capacity(capacity: int) -> None:
    conn = await asyncpg.connect(ASYNC_PG_DSN)
    try:
        await conn.execute(
            """
            UPDATE rate_limit_rules r
               SET capacity = $1
              FROM api_keys ak
             WHERE r.api_key_id = ak.id
               AND ak.api_key = $2
            """,
            capacity, API_KEY,
        )
    finally:
        await conn.close()


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL) as c:
        old_limit = await _get_limit(c)
    print(f"Current capacity for {API_KEY}: {old_limit}")

    await _set_capacity(NEW_CAPACITY)
    print(f"Updated capacity in Postgres to: {NEW_CAPACITY}")

    t0 = time.time()
    stale = 0
    async with httpx.AsyncClient(base_url=BASE_URL) as c:
        for _ in range(200):
            if await _get_limit(c) == old_limit:
                stale += 1
    elapsed_ms = (time.time() - t0) * 1000

    print(f"{stale}/200 responses used the old capacity ({elapsed_ms:.0f} ms elapsed)")

    await _set_capacity(old_limit)
    print(f"Restored capacity to: {old_limit}")


if __name__ == "__main__":
    asyncio.run(main())