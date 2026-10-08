"""Auth endpoints throttle repeated calls from the same client."""

from fastapi.testclient import TestClient


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
