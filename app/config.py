from typing import Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/traffic"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, v: str | None) -> str:
        if not v:
            return "postgresql+asyncpg://postgres:postgres@localhost:5432/traffic"
        # Cloud providers (Railway, Render, Heroku) often provide postgres:// or postgresql://
        # SQLAlchemy with asyncpg requires postgresql+asyncpg://
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_SOCKET_TIMEOUT: int = 5

    # App
    APP_NAME: str = "API Traffic Control"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "info"

    # Rate limiter defaults (safety net for incomplete rules)
    DEFAULT_CAPACITY: int = 100
    DEFAULT_REFILL_RATE: float = 1.67
    DEFAULT_WINDOW_SECONDS: int = 60
    DEFAULT_ALGORITHM: Literal["fixed_window", "token_bucket"] = "token_bucket"


settings = Settings()