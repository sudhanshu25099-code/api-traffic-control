from pathlib import Path

import redis.asyncio as redis

from app.config import settings

LUA_DIR = Path(__file__).parent / "lua"
SCRIPT_NAMES = ("fixed_window", "token_bucket")

_client: redis.Redis | None = None
_scripts: dict[str, str] = {}  # name -> SHA1


async def connect() -> None:
    """Called from FastAPI lifespan startup."""
    global _client
    _client = redis.from_url(
        settings.REDIS_URL,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        decode_responses=True,
    )
    for name in SCRIPT_NAMES:
        source = (LUA_DIR / f"{name}.lua").read_text()
        _scripts[name] = await _client.script_load(source)


async def close() -> None:
    if _client is not None:
        await _client.aclose()


def client() -> redis.Redis:
    assert _client is not None, "Redis client not initialised"
    return _client


async def evalsha(name: str, keys: list[str], args: list) -> list:
    """Run a cached Lua script by SHA. Re-loads on NOSCRIPT."""
    try:
        return await client().evalsha(_scripts[name], len(keys), *keys, *args)
    except redis.ResponseError as exc:
        if "NOSCRIPT" not in str(exc):
            raise
        source = (LUA_DIR / f"{name}.lua").read_text()
        _scripts[name] = await client().script_load(source)
        return await client().evalsha(_scripts[name], len(keys), *keys, *args)