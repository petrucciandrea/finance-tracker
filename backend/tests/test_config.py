"""Production refuses to boot on unsafe settings."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SAFE = {
    "database_url": "postgresql+psycopg://u:p@db:5432/x",
    "jwt_secret_key": "a" * 40,
    "environment": "production",
    "debug": False,
    "registration_mode": "open",
    "cors_allowed_origins": ["https://app.example.com"],
    # Explicit Nones: the container's own env vars would otherwise fill them in.
    "admin_email": None,
    "smtp_host": None,
    "smtp_from": None,
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**SAFE, **overrides})  # type: ignore[arg-type]


def test_safe_production_settings_boot() -> None:
    assert _settings().is_production


@pytest.mark.parametrize(
    "overrides",
    [
        {"debug": True},
        {"jwt_secret_key": "replace-this-with-a-random-256-bit-secret"},
        {"jwt_secret_key": "short"},
        {"cors_allowed_origins": ["*"]},
        {"registration_mode": "approval"},  # no admin email / SMTP
    ],
)
def test_unsafe_production_settings_are_refused(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)


def test_approval_mode_boots_once_email_is_configured() -> None:
    assert _settings(
        registration_mode="approval",
        admin_email="admin@example.com",
        smtp_host="smtp.example.com",
        smtp_from="noreply@example.com",
    )


def test_development_is_not_restricted() -> None:
    assert _settings(environment="development", debug=True, jwt_secret_key="x")
