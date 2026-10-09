"""Auth endpoints throttle repeated calls from the same client."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def test_login_is_throttled_after_too_many_attempts(client: TestClient) -> None:
    creds = {"email": "nobody@example.com", "password": "wrong-password"}

    statuses = [client.post("/api/v1/auth/login", json=creds).status_code for _ in range(11)]

    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


def test_throttled_response_uses_the_error_envelope_and_retry_after(client: TestClient) -> None:
    creds = {"email": "nobody@example.com", "password": "wrong-password"}
    for _ in range(10):
        client.post("/api/v1/auth/login", json=creds)

    response = client.post("/api/v1/auth/login", json=creds)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) > 0


def test_register_is_throttled(client: TestClient) -> None:
    def attempt(i: int) -> int:
        return client.post(
            "/api/v1/auth/register",
            json={
                "email": f"spam{i}@example.com",
                "password": "password123",
                "base_currency": "EUR",
                "accept_terms": True,
            },
        ).status_code

    statuses = [attempt(i) for i in range(6)]

    assert statuses == [201] * 5 + [429]


def test_limits_are_per_route(client: TestClient) -> None:
    creds = {"email": "nobody@example.com", "password": "wrong-password"}
    for _ in range(11):
        client.post("/api/v1/auth/login", json=creds)

    # Exhausting login must not lock the client out of other routes.
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "x"})

    assert response.status_code == 401


def _spoofed_logins(client: TestClient, count: int) -> list[int]:
    creds = {"email": "nobody@example.com", "password": "wrong-password"}
    return [
        client.post(
            "/api/v1/auth/login", json=creds, headers={"X-Forwarded-For": f"9.9.9.{i}"}
        ).status_code
        for i in range(count)
    ]


def test_forwarded_for_is_ignored_when_no_proxy_is_configured(client: TestClient) -> None:
    # Default (0 proxies): the header is attacker-controlled, so it must not
    # let anyone mint a fresh bucket per request.
    assert _spoofed_logins(client, 11)[-1] == 429


def test_with_one_trusted_proxy_the_rightmost_entry_is_the_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    creds = {"email": "nobody@example.com", "password": "wrong-password"}

    # The proxy appends the real address; whatever the caller put to its left is ignored.
    statuses = [
        client.post(
            "/api/v1/auth/login",
            json=creds,
            headers={"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.7"},
        ).status_code
        for i in range(11)
    ]

    assert statuses[-1] == 429


def test_distinct_real_clients_behind_the_proxy_get_separate_buckets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    creds = {"email": "nobody@example.com", "password": "wrong-password"}
    for _ in range(10):
        client.post("/api/v1/auth/login", json=creds, headers={"X-Forwarded-For": "203.0.113.7"})

    other = client.post(
        "/api/v1/auth/login", json=creds, headers={"X-Forwarded-For": "198.51.100.9"}
    )

    assert other.status_code == 401  # not throttled with someone else's bucket
