"""
Application settings, loaded from environment variables / a .env file.

Single source of truth for configuration used by both the FastAPI app
and Alembic's env.py (via `from app.core.config import settings`).
"""

from functools import lru_cache

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Finance Tracker"
    environment: str = Field(default="development")  # development | test | production
    debug: bool = Field(default=False)

    # --- Database ---
    database_url: PostgresDsn = Field(
        ..., description="e.g. postgresql+psycopg://user:pass@localhost:5432/finance_tracker"
    )
    # Separate URL for the test DB (used by pytest fixtures / db_test service)
    test_database_url: PostgresDsn | None = None

    # --- Auth / JWT ---
    jwt_secret_key: str = Field(..., description="Random 256-bit secret, keep out of git")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # --- CORS ---
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- External APIs ---
    exchange_rate_api_base_url: str = "https://api.frankfurter.app"
    alpha_vantage_api_key: str | None = None  # needed later, phase 3
    coingecko_api_key: str | None = None  # optional, phase 3

    # --- Default currency (used before a user sets their own) ---
    default_base_currency: str = "EUR"

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "test", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got {v!r}")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings instance.

    Using a function (rather than a bare module-level `Settings()`) makes it
    easy to override in tests via dependency overrides / monkeypatching the
    cache, instead of mutating a shared global.
    """
    return Settings()


# Module-level convenience instance for places that just want `settings.x`
# (e.g. alembic/env.py). Prefer `get_settings()` as a FastAPI dependency
# inside request handlers so it can be overridden in tests.
settings = get_settings()
