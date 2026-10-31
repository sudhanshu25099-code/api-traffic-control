from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.middleware import RateLimitMiddleware
from app.redis_client import close as redis_close
from app.redis_client import connect as redis_connect
from app.routers import admin, dummy_api


@asynccontextmanager
async def lifespan(app: FastAPI):
    await redis_connect()          # load Lua scripts once
    yield
    await redis_close()
    await engine.dispose()


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

# Register the ASGI middleware (not @app.middleware("http") — that's BaseHTTPMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(dummy_api.router)
app.include_router(admin.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}