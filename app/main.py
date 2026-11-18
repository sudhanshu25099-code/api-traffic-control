from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine, init_db
from app.middleware import RateLimitMiddleware
from app.redis_client import close as redis_close
from app.redis_client import connect as redis_connect
from app.routers import admin, analytics, dummy_api


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()                # auto-create tables and seed data if needed
    try:
        await redis_connect()      # load Lua scripts once
    except Exception as exc:
        print(f"[lifespan] Warning: Redis connection deferred: {exc}")
    yield
    await redis_close()
    await engine.dispose()


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

# Register the ASGI middleware (not @app.middleware("http") — that's BaseHTTPMiddleware)
app.add_middleware(RateLimitMiddleware)

# CORS — outermost middleware so OPTIONS preflight and rate limit responses carry CORS headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"],
)

app.include_router(dummy_api.router)
app.include_router(admin.router)
app.include_router(analytics.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


# Mount the Hallmark Frontend directly at the root for unified single-URL deployment
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
