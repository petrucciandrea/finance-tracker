"""
Tests for the auth flow: register, login, refresh rotation, logout
revocation, and access to protected endpoints.
"""

from fastapi.testclient import TestClient


def test_register_creates_user(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "new.user@example.com", "password": "password123", "base_currency": "EUR"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.user@example.com"
    assert body["base_currency"] == "EUR"
    assert "password" not in body  # never echo the password back, hashed or not


def test_register_rejects_duplicate_email(client: TestClient, registered_user: dict) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": registered_user["email"],
            "password": "different-password",
            "base_currency": "USD",
        },
    )

    assert response.status_code == 409


def test_login_with_correct_credentials_returns_tokens(client: TestClient, registered_user: dict) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


def test_login_with_wrong_password_returns_401(client: TestClient, registered_user: dict) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_login_with_unknown_email_returns_same_401_as_wrong_password(client: TestClient) -> None:
    # Same status/detail as a wrong password — asserts we don't leak whether
    # the email exists (see auth_router's comment on this).
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever123"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Incorrect email or password"


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user(client: TestClient, registered_user: dict) -> None:
    response = client.get("/api/v1/auth/me", headers=registered_user["auth_headers"])

    assert response.status_code == 200
    assert response.json()["email"] == registered_user["email"]


def test_refresh_rotates_token_and_old_one_becomes_invalid(
    client: TestClient, registered_user: dict
) -> None:
    old_refresh_token = registered_user["refresh_token"]

    first_refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert first_refresh.status_code == 200
    new_tokens = first_refresh.json()
    assert new_tokens["refresh_token"] != old_refresh_token

    # Replaying the original (now-rotated) refresh token must fail.
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert replay.status_code == 401


def test_logout_revokes_refresh_token(client: TestClient, registered_user: dict) -> None:
    logout_response = client.post(
        "/api/v1/auth/logout", json={"refresh_token": registered_user["refresh_token"]}
    )
    assert logout_response.status_code == 204

    refresh_after_logout = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": registered_user["refresh_token"]}
    )
    assert refresh_after_logout.status_code == 401
