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


def test_login_with_correct_credentials_returns_tokens(
    client: TestClient, registered_user: dict
) -> None:
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


def test_password_longer_than_bcrypt_limit_registers_and_logs_in(client: TestClient) -> None:
    # bcrypt>=5 raises on input over 72 bytes; security.py truncates first,
    # as passlib did, so this must stay a normal register/login, not a 500.
    password = "ü" * 50  # 100 bytes in UTF-8
    credentials = {"email": "long.password@example.com", "password": password}

    register = client.post("/api/v1/auth/register", json={**credentials, "base_currency": "EUR"})
    login = client.post("/api/v1/auth/login", json=credentials)

    assert register.status_code == 201
    assert login.status_code == 200


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


def test_update_me_changes_email_and_base_currency(
    client: TestClient, registered_user: dict
) -> None:
    response = client.patch(
        "/api/v1/auth/me",
        json={"email": "updated@example.com", "base_currency": "USD"},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "updated@example.com"
    assert body["base_currency"] == "USD"


def test_update_me_sets_anagrafica_fields(client: TestClient, registered_user: dict) -> None:
    response = client.patch(
        "/api/v1/auth/me",
        json={"first_name": "Mario", "last_name": "Rossi", "date_of_birth": "1990-05-20"},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Mario"
    assert body["last_name"] == "Rossi"
    assert body["date_of_birth"] == "1990-05-20"


def test_update_me_can_clear_one_anagrafica_field_without_touching_others(
    client: TestClient, registered_user: dict
) -> None:
    setup = client.patch(
        "/api/v1/auth/me",
        json={"first_name": "Mario", "last_name": "Rossi"},
        headers=registered_user["auth_headers"],
    )
    assert setup.status_code == 200

    response = client.patch(
        "/api/v1/auth/me",
        json={"last_name": None},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Mario"
    assert body["last_name"] is None


def test_update_me_defaults_anagrafica_fields_to_null(
    client: TestClient, registered_user: dict
) -> None:
    response = client.get("/api/v1/auth/me", headers=registered_user["auth_headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] is None
    assert body["last_name"] is None
    assert body["date_of_birth"] is None


def test_update_me_rejects_email_already_taken(client: TestClient, registered_user: dict) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={"email": "other.user@example.com", "password": "password123", "base_currency": "EUR"},
    )
    assert other.status_code == 201

    response = client.patch(
        "/api/v1/auth/me",
        json={"email": "other.user@example.com"},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 409


def test_update_me_requires_authentication(client: TestClient) -> None:
    response = client.patch("/api/v1/auth/me", json={"base_currency": "USD"})
    assert response.status_code == 401


def test_change_password_with_correct_current_password(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        "/api/v1/auth/me/password",
        json={"current_password": registered_user["password"], "new_password": "new-password-456"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 204

    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": "new-password-456"},
    )
    assert new_login.status_code == 200


def test_change_password_with_wrong_current_password_returns_401(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "wrong-password", "new_password": "new-password-456"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 401
