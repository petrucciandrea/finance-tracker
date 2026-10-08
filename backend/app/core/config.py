"""
Application settings, loaded from environment variables / a .env file.

Single source of truth for configuration used by both the FastAPI app
and Alembic's env.py (via `from app.core.config import settings`).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
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

    # --- Registration ---
    # "approval": a new account is created pending and can't log in until the
    # admin approves it from the link emailed to `admin_email`. "open": anyone
    # can register and is approved immediately. Defaults to the closed mode so
    # a deploy that forgets to configure it is not accidentally open.
    registration_mode: Literal["approval", "open"] = "approval"
    admin_email: str | None = None
    approval_token_expire_days: int = 14
    # Public URL of the frontend: the approval/login links in emails point here.
    frontend_base_url: str = "http://localhost:5173"

    # --- Email (SMTP) ---
    # Unset host = emails are only logged, never sent (development).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True

    # --- CORS ---
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- External APIs ---
    exchange_rate_api_base_url: str = "https://api.frankfurter.app"
    # phase 3: stock/ETF prices. Unofficial endpoint, no API key/signup — but
    # also no documented quota or support guarantee; swap providers here if
    # it ever gets blocked or changes shape.
    yahoo_finance_api_base_url: str = "https://query1.finance.yahoo.com/v8/finance/chart"
    coingecko_api_key: str | None = None  # phase 3: crypto prices, optional (free tier needs none)
    coingecko_api_base_url: str = "https://api.coingecko.com/api/v3"

    # --- Default currency (used before a user sets their own) ---
    default_base_currency: str = "EUR"

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "test", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got {v!r}")
        return v

    @model_validator(mode="after")
    def validate_production_setup(self) -> "Settings":
        # Production refuses to boot on settings that are unsafe or incomplete,
        # rather than serving traffic and failing quietly later.
        if not self.is_production:
            return self
        problems = []
        if self.debug:
            # debug=True returns full tracebacks (bypassing the error handler)
            # and logs every SQL statement with its parameters.
            problems.append("DEBUG must be false")
        if len(self.jwt_secret_key) < 32 or self.jwt_secret_key.startswith("replace-this"):
            problems.append("JWT_SECRET_KEY must be a random value of at least 32 characters")
        if "*" in self.cors_allowed_origins:
            problems.append("CORS_ALLOWED_ORIGINS must list explicit origins, not '*'")
        if self.registration_mode == "approval" and not (
            # Approval mode with nowhere to send the request would leave every
            # new account pending forever with no one told.
            self.admin_email and self.smtp_host and self.smtp_from
        ):
            problems.append("REGISTRATION_MODE=approval needs ADMIN_EMAIL, SMTP_HOST and SMTP_FROM")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

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
    # pydantic-settings populates `database_url` and `jwt_secret_key` from
    # the environment / .env, which mypy can't see from the constructor call.
    return Settings()  # type: ignore[call-arg]


# Module-level convenience instance for places that just want `settings.x`
# (e.g. alembic/env.py). Prefer `get_settings()` as a FastAPI dependency
# inside request handlers so it can be overridden in tests.
settings = get_settings()
