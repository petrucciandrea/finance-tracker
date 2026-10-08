"""Email verification and password reset."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token, create_password_reset_token

CREDS = {"email": "someone@example.com", "password": "a-secure-password-123"}
PAYLOAD = {**CREDS, "base_currency": "EUR", "accept_terms": True}


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    monkeypatch.setattr(settings, "require_email_verification", True)
    box: list[dict] = []
    monkeypatch.setattr(
        "app.routers.auth.send_email",
        lambda to, subject, body: box.append({"to": to, "subject": subject, "body": body}),
    )
    return box


def _token(message: dict) -> str:
    return message["body"].split("#token=")[1].split()[0]


def _register(client: TestClient) -> dict:
    response = client.post("/api/v1/auth/register", json=PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()


def _login(client: TestClient, password: str = CREDS["password"]):
    return client.post("/api/v1/auth/login", json={"email": CREDS["email"], "password": password})


# --- email verification ---------------------------------------------------


def test_unverified_user_cannot_log_in_until_the_link_is_used(
    client: TestClient, sent: list[dict]
) -> None:
    assert _register(client)["email_verified_at"] is None
    assert len(sent) == 1 and sent[0]["to"] == CREDS["email"]

    blocked = _login(client)
    verify = client.post("/api/v1/auth/email/verify", json={"token": _token(sent[0])})

    assert blocked.status_code == 403
    assert blocked.json()["error"]["message"] == "EMAIL_NOT_VERIFIED"
    assert verify.status_code == 204
    assert _login(client).status_code == 200


def test_wrong_password_on_unverified_account_still_401(
    client: TestClient, sent: list[dict]
) -> None:
    _register(client)

    assert _login(client, "not-the-password").status_code == 401


def test_verifying_twice_is_harmless(client: TestClient, sent: list[dict]) -> None:
    _register(client)
    body = {"token": _token(sent[0])}

    assert client.post("/api/v1/auth/email/verify", json=body).status_code == 204
    assert client.post("/api/v1/auth/email/verify", json=body).status_code == 204


def test_garbage_or_wrong_type_verification_token_is_rejected(
    client: TestClient, sent: list[dict]
) -> None:
    user = _register(client)

    for token in ("nope", create_access_token(user["id"])):
        response = client.post("/api/v1/auth/email/verify", json={"token": token})
        assert response.status_code == 401


def test_resend_is_uniform_and_only_mails_unverified_accounts(
    client: TestClient, sent: list[dict]
) -> None:
    _register(client)
    sent.clear()

    known = client.post("/api/v1/auth/email/resend-verification", json={"email": CREDS["email"]})
    unknown = client.post(
        "/api/v1/auth/email/resend-verification", json={"email": "no@example.com"}
    )

    assert known.status_code == unknown.status_code == 202
    assert [m["to"] for m in sent] == [CREDS["email"]]


def test_verification_off_means_nothing_to_confirm(client: TestClient) -> None:
    assert _register(client)["email_verified_at"] is not None
    assert _login(client).status_code == 200


# --- password reset ---------------------------------------------------------


def _verified_user(client: TestClient, sent: list[dict]) -> None:
    _register(client)
    client.post("/api/v1/auth/email/verify", json={"token": _token(sent[0])})
    sent.clear()


def test_reset_flow_changes_the_password_and_the_link_works_once(
    client: TestClient, sent: list[dict]
) -> None:
    _verified_user(client, sent)
    client.post("/api/v1/auth/password-reset/request", json={"email": CREDS["email"]})
    token = _token(sent[0])

    first = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "brand-new-pass-1"},
    )
    second = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "another-pass-22"},
    )

    assert first.status_code == 204
    assert second.status_code == 401  # the password changed, so the link is spent
    assert _login(client).status_code == 401
    assert _login(client, "brand-new-pass-1").status_code == 200


def test_reset_request_is_uniform_for_unknown_addresses(
    client: TestClient, sent: list[dict]
) -> None:
    _verified_user(client, sent)

    known = client.post("/api/v1/auth/password-reset/request", json={"email": CREDS["email"]})
    unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "no@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert [m["to"] for m in sent] == [CREDS["email"]]


def test_reset_revokes_existing_sessions(client: TestClient, sent: list[dict]) -> None:
    _verified_user(client, sent)
    refresh = _login(client).json()["refresh_token"]
    client.post("/api/v1/auth/password-reset/request", json={"email": CREDS["email"]})

    client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": _token(sent[0]), "new_password": "brand-new-pass-1"},
    )

    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_reset_also_verifies_the_mailbox(client: TestClient, sent: list[dict]) -> None:
    _register(client)  # never clicks the verification link
    client.post("/api/v1/auth/password-reset/request", json={"email": CREDS["email"]})
    reset = next(m for m in sent if "reimposta" in m["subject"])

    client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": _token(reset), "new_password": "brand-new-pass-1"},
    )

    assert _login(client, "brand-new-pass-1").status_code == 200


def test_reset_rejects_other_token_types_and_short_passwords(
    client: TestClient, sent: list[dict]
) -> None:
    user = _register(client)

    forged = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": create_access_token(user["id"]), "new_password": "brand-new-pass-1"},
    )
    short = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": create_password_reset_token(user["id"], "x"), "new_password": "short"},
    )

    assert forged.status_code == 401
    assert short.status_code == 422


def test_reset_request_is_rate_limited(client: TestClient, sent: list[dict]) -> None:
    body = {"email": "no@example.com"}

    statuses = [
        client.post("/api/v1/auth/password-reset/request", json=body).status_code for _ in range(6)
    ]

    assert statuses == [202] * 5 + [429]


# --- approval mode: one email, not two ------------------------------------------


@pytest.fixture
def approval_flow(sent: list[dict], monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    monkeypatch.setattr(settings, "registration_mode", "approval")
    monkeypatch.setattr(settings, "admin_email", "admin@example.com")
    return sent


def _decide(client: TestClient, admin_message: dict, decision: str):
    return client.post(
        "/api/v1/auth/approvals/decision",
        json={"token": _token(admin_message), "decision": decision},
    )


def test_with_approval_the_user_gets_nothing_until_approved(
    client: TestClient, approval_flow: list[dict]
) -> None:
    _register(client)

    assert [m["to"] for m in approval_flow] == ["admin@example.com"]


def test_approval_sends_a_single_email_that_also_confirms_the_address(
    client: TestClient, approval_flow: list[dict]
) -> None:
    _register(client)
    admin_message = approval_flow[0]

    _decide(client, admin_message, "approve")

    to_user = [m for m in approval_flow if m["to"] == CREDS["email"]]
    assert len(to_user) == 1
    assert "approvato" in to_user[0]["subject"]
    assert "/verifica-email#token=" in to_user[0]["body"]
    # One click on that link is all that's left before logging in.
    assert _login(client).status_code == 403
    client.post("/api/v1/auth/email/verify", json={"token": _token(to_user[0])})
    assert _login(client).status_code == 200


def test_pending_user_is_told_about_approval_not_verification(
    client: TestClient, approval_flow: list[dict]
) -> None:
    _register(client)

    response = _login(client)

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "ACCOUNT_PENDING_APPROVAL"


def test_resend_verification_waits_for_approval(
    client: TestClient, approval_flow: list[dict]
) -> None:
    _register(client)
    approval_flow.clear()

    client.post("/api/v1/auth/email/resend-verification", json={"email": CREDS["email"]})

    assert approval_flow == []


def test_rejection_sends_one_email_and_no_confirmation_link(
    client: TestClient, approval_flow: list[dict]
) -> None:
    _register(client)

    _decide(client, approval_flow[0], "reject")

    to_user = [m for m in approval_flow if m["to"] == CREDS["email"]]
    assert len(to_user) == 1
    assert "#token=" not in to_user[0]["body"]
