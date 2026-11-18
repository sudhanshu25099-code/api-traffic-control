from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from typing import AsyncGenerator
from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    echo=settings.DB_ECHO,
)

SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def init_db() -> None:
    """Auto-run schema.sql and seed.sql on startup if tables are not initialized."""
    from pathlib import Path
    import sqlalchemy as sa

    sql_dir = Path(__file__).resolve().parent.parent / "sql"
    schema_file = sql_dir / "schema.sql"
    seed_file = sql_dir / "seed.sql"

    try:
        async with engine.begin() as conn:
            if schema_file.exists():
                schema_sql = schema_file.read_text(encoding="utf-8")
                for statement in schema_sql.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        await conn.execute(sa.text(stmt))
            if seed_file.exists():
                seed_sql = seed_file.read_text(encoding="utf-8")
                for statement in seed_sql.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        await conn.execute(sa.text(stmt))
    except Exception as exc:
        # Do not crash if DB permissions or connection is still warming up
        print(f"[init_db] Warning during DB initialization: {exc}")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Yields an AsyncSession bound to the pool."""
    async with SessionLocal() as session:
        yield session