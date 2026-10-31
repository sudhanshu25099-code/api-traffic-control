import asyncio

from fastapi import APIRouter, Security
from fastapi.security import APIKeyHeader

router = APIRouter(prefix="/api", tags=["demo"])

# Define the security scheme here
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

RL_HEADER_DOC = {
    "X-RateLimit-Limit":     {"schema": {"type": "integer"}, "description": "Max requests in window"},
    "X-RateLimit-Remaining": {"schema": {"type": "integer"}, "description": "Requests left in window"},
    "X-RateLimit-Reset":     {"schema": {"type": "integer"}, "description": "Unix epoch of window reset"},
}

@router.get(
    "/data",
    summary="Fast demo endpoint used in Swagger and Locust",
    responses={
        200: {"description": "OK",       "headers": RL_HEADER_DOC},
        429: {"description": "Rate limit exceeded"},
    },
)
async def get_data(api_key: str = Security(api_key_header)) -> dict:
    return {"message": "ok"}

@router.get(
    "/heavy-computation",
    summary="Artificially slow endpoint used in Locust to skew p95",
    responses={
        200: {"description": "OK", "headers": RL_HEADER_DOC},
        429: {"description": "Rate limit exceeded"},
    },
)
async def heavy_computation(api_key: str = Security(api_key_header)) -> dict:
    await asyncio.sleep(0.05)
    return {"message": "done"}