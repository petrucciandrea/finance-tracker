"""Registration can be closed; accounts are then made with the create_user command."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import create_user
from app.core.config import Settings, settings
from app.models import User
from app.services import email as email_service

PAYLOAD = {
    "email": "someone@example.com",
    "password": "a-secure-password-123",
    "base_currency": "EUR",
    "accept_terms": True,
}


@pytest.fixture
def closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "registration_mode", "closed")


def test_closed_registration_is_refused(client: TestClient, closed: None) -> None:
    response = client.post("/api/v1/auth/register", json=PAYLOAD)

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "REGISTRATION_CLOSED"


def test_closed_registration_creates_nothing(
    client: TestClient, closed: None, db_session: Session
) -> None:
    client.post("/api/v1/auth/register", json=PAYLOAD)

    assert db_session.query(User).filter_by(email=PAYLOAD["email"]).count() == 0


def test_existing_users_can_still_log_in_when_registration_is_closed(
    client: TestClient, registered_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "registration_mode", "closed")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )

    assert response.status_code == 200


@pytest.mark.parametrize("mode", ["closed", "approval", "open"])
def test_public_config_reports_the_mode(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(settings, "registration_mode", mode)

    body = client.get("/api/v1/auth/config").json()

    assert body["registration_mode"] == mode


def test_public_config_reports_whether_email_works(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)
    assert client.get("/api/v1/auth/config").json()["email_enabled"] is False

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "noreply@example.com")
    assert client.get("/api/v1/auth/config").json()["email_enabled"] is True


def test_closed_production_boots_without_any_email_settings() -> None:
    Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql://u:p@db/x",
        jwt_secret_key="a" * 40,
        environment="production",
        debug=False,
        registration_mode="closed",
        admin_email=None,
        smtp_host=None,
        smtp_from=None,
    )


# --- email never logs links in production ------------------------------------------------


def test_production_log_never_holds_the_message_body(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "environment", "production")

    with caplog.at_level(logging.WARNING):
        email_service.send_email("a@example.com", "Reset", "https://x/reimposta#token=SECRET")

    assert "not sent" in caplog.text
    assert "SECRET" not in caplog.text


def test_development_log_keeps_the_body_for_local_work(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "environment", "development")

    with caplog.at_level(logging.WARNING):
        email_service.send_email("a@example.com", "Reset", "https://x/reimposta#token=SECRET")

    assert "SECRET" in caplog.text


# --- create_user -------------------------------------------------------------------------


class _Borrowed:
    """Lets the command use the test's session without closing it."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def run_create_user(monkeypatch: pytest.MonkeyPatch, db_session: Session):
    def run(args: list[str], *passwords: str) -> None:
        answers = iter(passwords)
        monkeypatch.setattr(create_user.getpass, "getpass", lambda prompt="": next(answers))
        monkeypatch.setattr(create_user, "SessionLocal", lambda: _Borrowed(db_session))
        create_user.main(args)

    return run


def test_create_user_makes_an_approved_verified_account_that_can_log_in(
    client: TestClient, closed: None, db_session: Session, run_create_user
) -> None:
    run_create_user(["Owner@Example.com"], "a-secure-password-123", "a-secure-password-123")

    user = db_session.query(User).filter_by(email="owner@example.com").one()
    assert user.approval_status == "approved"
    assert user.email_verified_at is not None
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "a-secure-password-123"},
    )
    assert login.status_code == 200


def test_create_user_refuses_mismatched_short_unknown_currency_and_duplicates(
    db_session: Session, run_create_user
) -> None:
    with pytest.raises(SystemExit):
        run_create_user(["a@example.com"], "a-secure-password-123", "different-password-1")
    with pytest.raises(SystemExit):
        run_create_user(["a@example.com"], "short", "short")
    with pytest.raises(SystemExit):
        run_create_user(
            ["a@example.com", "--currency", "ZZZ"],
            "a-secure-password-123",
            "a-secure-password-123",
        )
    run_create_user(["a@example.com"], "a-secure-password-123", "a-secure-password-123")
    with pytest.raises(SystemExit):
        run_create_user(["A@example.com"], "a-secure-password-123", "a-secure-password-123")

    assert db_session.query(User).filter_by(email="a@example.com").count() == 1
