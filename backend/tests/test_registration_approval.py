"""
Registration gating: in "approval" mode an account is pending until the admin
decides from the emailed link; "open" mode approves immediately.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token, create_approval_token
from app.models import User
from app.services import email as email_service

CREDS = {"email": "newcomer@example.com", "password": "a-secure-password-123"}


@pytest.fixture
def approval_mode(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    monkeypatch.setattr(settings, "registration_mode", "approval")
    monkeypatch.setattr(settings, "admin_email", "admin@example.com")
    sent: list[dict] = []

    def fake_send(to: str, subject: str, body: str) -> None:
        sent.append({"to": to, "subject": subject, "body": body})

    # Patched where the router looks it up, not in the email module.
    monkeypatch.setattr("app.routers.auth.send_email", fake_send)
    return sent


def _register(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/register", json={**CREDS, "base_currency": "EUR", "accept_terms": True}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(client: TestClient):
    return client.post("/api/v1/auth/login", json=CREDS)


def _token_from(body: str) -> str:
    return body.split("#token=")[1].split()[0]


def test_open_mode_approves_immediately(client: TestClient) -> None:
    assert _register(client)["approval_status"] == "approved"
    assert _login(client).status_code == 200


def test_approval_mode_registers_pending_and_emails_admin(
    client: TestClient, approval_mode: list[dict]
) -> None:
    assert _register(client)["approval_status"] == "pending"

    assert len(approval_mode) == 1
    assert approval_mode[0]["to"] == "admin@example.com"
    assert CREDS["email"] in approval_mode[0]["body"]
    assert "/approvazione#token=" in approval_mode[0]["body"]


def test_pending_user_cannot_log_in(client: TestClient, approval_mode: list[dict]) -> None:
    _register(client)

    response = _login(client)

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "ACCOUNT_PENDING_APPROVAL"


def test_wrong_password_on_pending_account_still_401(
    client: TestClient, approval_mode: list[dict]
) -> None:
    # The pending/rejected answer must not reveal that the email exists.
    _register(client)

    response = client.post(
        "/api/v1/auth/login", json={"email": CREDS["email"], "password": "not-the-password"}
    )

    assert response.status_code == 401


def test_approve_then_login_and_user_is_notified(
    client: TestClient, approval_mode: list[dict]
) -> None:
    _register(client)
    token = _token_from(approval_mode[0]["body"])

    decision = client.post(
        "/api/v1/auth/approvals/decision", json={"token": token, "decision": "approve"}
    )

    assert decision.status_code == 200
    assert decision.json()["approval_status"] == "approved"
    assert _login(client).status_code == 200
    assert approval_mode[1]["to"] == CREDS["email"]


def test_reject_blocks_login(client: TestClient, approval_mode: list[dict]) -> None:
    _register(client)
    token = _token_from(approval_mode[0]["body"])

    client.post("/api/v1/auth/approvals/decision", json={"token": token, "decision": "reject"})

    response = _login(client)
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "ACCOUNT_REJECTED"


def test_decision_cannot_be_changed_once_made(
    client: TestClient, approval_mode: list[dict]
) -> None:
    _register(client)
    token = _token_from(approval_mode[0]["body"])
    client.post("/api/v1/auth/approvals/decision", json={"token": token, "decision": "approve"})

    again = client.post(
        "/api/v1/auth/approvals/decision", json={"token": token, "decision": "reject"}
    )

    assert again.status_code == 409
    assert _login(client).status_code == 200


def test_preview_does_not_change_status(client: TestClient, approval_mode: list[dict]) -> None:
    _register(client)
    token = _token_from(approval_mode[0]["body"])

    preview = client.post("/api/v1/auth/approvals/preview", json={"token": token})

    assert preview.status_code == 200
    assert preview.json()["email"] == CREDS["email"]
    assert preview.json()["approval_status"] == "pending"
    assert _login(client).status_code == 403


def test_garbage_token_is_rejected(client: TestClient, approval_mode: list[dict]) -> None:
    response = client.post(
        "/api/v1/auth/approvals/decision", json={"token": "nope", "decision": "approve"}
    )

    assert response.status_code == 401


def test_access_token_is_not_an_approval_token(
    client: TestClient, approval_mode: list[dict]
) -> None:
    user = _register(client)

    response = client.post(
        "/api/v1/auth/approvals/decision",
        json={"token": create_access_token(user["id"]), "decision": "approve"},
    )

    assert response.status_code == 401


def test_approval_token_is_not_an_access_token(
    client: TestClient, approval_mode: list[dict]
) -> None:
    user = _register(client)
    token = create_approval_token(user["id"])

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_rejected_user_with_a_live_access_token_is_locked_out(
    client: TestClient, db_session, approval_mode: list[dict]
) -> None:
    # A token issued while approved must stop working if the status changes.
    user = _register(client)
    access = create_access_token(user["id"])
    row = db_session.get(User, user["id"])
    row.approval_status = "rejected"
    db_session.commit()

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})

    assert response.status_code == 401


def test_smtp_failure_does_not_break_registration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "registration_mode", "approval")
    monkeypatch.setattr(settings, "admin_email", "admin@example.com")
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 1)  # nothing listens here
    monkeypatch.setattr(settings, "smtp_from", "noreply@example.com")

    assert _register(client)["approval_status"] == "pending"
    # And the module itself swallowed the connection error.
    email_service.send_email("a@example.com", "s", "b")
