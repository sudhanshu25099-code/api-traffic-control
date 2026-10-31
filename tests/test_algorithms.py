"""
Run with:  pytest tests/test_algorithms.py -v

Unit tests — no DB / Redis required.
Integration tests — require a live app at http://localhost:8000; skipped
unless INTEGRATION=1 is set.
"""
import asyncio
import os

import httpx
import pytest

from app.limiters.fixed_window import InProcessFixedWindow
from app.limiters.token_bucket import InProcessTokenBucket


# ---------- Unit: in-process limiters ----------

@pytest.mark.asyncio
async def test_fixed_window_allows_then_rejects():
    limiter = InProcessFixedWindow()
    results = []
    for _ in range(6):
        d = await limiter.check("k1", capacity=5, window_seconds=60)
        results.append(d.allowed)
    assert results == [True, True, True, True, True, False]


@pytest.mark.asyncio
async def test_fixed_window_race_condition():
    """
    The in-process limiter is not atomic. Under concurrency it allows
    MORE than `capacity` requests, which is exactly why we need Lua.
    """
    limiter = InProcessFixedWindow()

    async def one():
        return (await limiter.check("race", capacity=10, window_seconds=60)).allowed

    results = await asyncio.gather(*[one() for _ in range(20)])
    allowed = sum(results)
    print(f"\n  Allowed: {allowed}/20 (limit was 10)")
    assert allowed > 10, f"Expected race condition, but only {allowed} passed"


@pytest.mark.asyncio
async def test_token_bucket_refill():
    limiter = InProcessTokenBucket()

    for _ in range(5):
        d = await limiter.check("tb", capacity=5, refill_rate=1.0)
        assert d.allowed

    d = await limiter.check("tb", capacity=5, refill_rate=1.0)
    assert not d.allowed

    await asyncio.sleep(1.1)
    d = await limiter.check("tb", capacity=5, refill_rate=1.0)
    assert d.allowed


@pytest.mark.asyncio
async def test_token_bucket_zero_capacity():
    limiter = InProcessTokenBucket()
    d = await limiter.check("zero", capacity=0, refill_rate=1.0)
    assert not d.allowed


# ---------- Integration: full stack ----------

INTEGRATION = os.getenv("INTEGRATION") == "1"
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


@pytest.mark.asyncio
@pytest.mark.skipif(not INTEGRATION, reason="Set INTEGRATION=1 to run")
async def test_headers_present():
    async with httpx.AsyncClient(base_url=BASE_URL) as c:
        r = await c.get("/api/data", headers={"X-API-Key": "demo-key"})
    assert r.status_code == 200
    assert "x-ratelimit-limit" in r.headers
    assert "x-ratelimit-remaining" in r.headers
    assert "x-ratelimit-reset" in r.headers


@pytest.mark.asyncio
@pytest.mark.skipif(not INTEGRATION, reason="Set INTEGRATION=1 to run")
async def test_unknown_key_returns_401():
    async with httpx.AsyncClient(base_url=BASE_URL) as c:
        r = await c.get("/api/data", headers={"X-API-Key": "no-such-key"})
    assert r.status_code == 401


@pytest.mark.asyncio
@pytest.mark.skipif(not INTEGRATION, reason="Set INTEGRATION=1 to run")
async def test_boundary_returns_429():
    # demo-key: capacity 5 / 60s → 5 pass, 6th is 429
    codes: list[int] = []
    async with httpx.AsyncClient(base_url=BASE_URL) as c:
        for _ in range(6):
            r = await c.get("/api/data", headers={"X-API-Key": "demo-key"})
            codes.append(r.status_code)
    assert codes[:5] == [200] * 5, codes
    assert codes[5] == 429, codes