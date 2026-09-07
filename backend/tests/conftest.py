"""
Shared pytest fixtures.

Strategy:
- One Postgres test DB (settings.test_database_url), tables created once per
  test session via Base.metadata.create_all.
- Each test runs inside a DB transaction that's rolled back afterwards, so
  tests don't leak data into each other and don't need manual cleanup.
- `client` overrides the app's `get_db` dependency to use that same
  per-test transaction, so requests made through the test client see
  exactly the data the test set up.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.deps import get_db
from app.main import app
from app.models import Base


@pytest.fixture(scope="session")
def engine():
    if settings.test_database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    eng = create_engine(str(settings.test_database_url))
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture
def db_session(engine) -> Generator[Session, None, None]:
    connection = engine.connect()
    transaction = connection.begin()
    TestSessionLocal = sessionmaker(bind=connection, expire_on_commit=False)
    session = TestSessionLocal()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()  # discards everything the test/request did
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _get_db_override() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def registered_user(client: TestClient) -> dict:
    """
    Creates a user and returns their credentials plus a ready-to-use auth
    header, since most tests below auth need an authenticated user anyway.
    """
    payload = {
        "email": "test.user@example.com",
        "password": "a-secure-password-123",
        "base_currency": "EUR",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text

    login_response = client.post(
        "/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_response.status_code == 200, login_response.text
    tokens = login_response.json()

    return {
        "email": payload["email"],
        "password": payload["password"],
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "auth_headers": {"Authorization": f"Bearer {tokens['access_token']}"},
    }
