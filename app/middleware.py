import json
import time
from typing import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.crud import get_rule_by_api_key
from app.database import SessionLocal
from app.models import Rule
from app.redis_client import evalsha

# Only these path prefixes are rate-limited. Docs, admin, health are open.
PROTECTED_PREFIXES = ("/api/",)


class RateLimitMiddleware:
    """Pure ASGI middleware — no BaseHTTPMiddleware overhead."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not any(path.startswith(p) for p in PROTECTED_PREFIXES):
            await self.app(scope, receive, send)
            return

        # --- Extract API key ---
        header_map = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        api_key = header_map.get("x-api-key", "").strip()
        if not api_key:
            await self._reject(scope, receive, send, 401, "Missing X-API-Key header")
            return

        # --- Fetch rule (async — never block the event loop) ---
        try:
            async with SessionLocal() as session:
                rule = await get_rule_by_api_key(session, api_key)
        except Exception as exc:
            await self._reject(scope, receive, send, 500, f"DB error: {exc}")
            return

        if rule is None:
            await self._reject(scope, receive, send, 401, "Unknown API key")
            return

        # --- Execute the limiter atomically in Redis ---
        try:
            allowed, remaining, reset_at, capacity = await self._evaluate(rule)
        except Exception as exc:
            await self._reject(scope, receive, send, 500, f"Limiter error: {exc}")
            return

        rl_headers: list[tuple[bytes, bytes]] = [
            (b"x-ratelimit-limit",     str(capacity).encode()),
            (b"x-ratelimit-remaining", str(remaining).encode()),
            (b"x-ratelimit-reset",     str(reset_at).encode()),
        ]

        if not allowed:
            retry_after = max(1, int(reset_at - time.time()))
            await self._reject(
                scope, receive, send, 429, "Rate limit exceeded",
                extra_headers=rl_headers + [(b"retry-after", str(retry_after).encode())],
            )
            return

        # --- Inject headers into the downstream response ---
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + rl_headers
            await send(message)

        await self.app(scope, receive, send_with_headers)

    async def _evaluate(self, rule: Rule) -> list:
        if rule.algorithm == "fixed_window":
            return await evalsha(
                "fixed_window",
                ["rl:fixed"],
                [rule.capacity, rule.window_seconds, rule.api_key],
            )
        return await evalsha(
            "token_bucket",
            ["rl:token"],
            [rule.capacity, rule.refill_rate, rule.api_key],
        )

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        detail: str,
        extra_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        body = json.dumps({"detail": detail}).encode()
        headers = [
            (b"content-type",   b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})