"""
Shared pytest fixtures.

Strategy:
- One Postgres test DB (settings.test_database_url), schema managed by Alembic
  (see `make migrate-test` / `make test`) — NOT by SQLAlchemy's create_all,
  since reference data like the seeded `currencies` rows only exists via the
  `0002_seed_currencies` migration. Tests assume the schema is already at
  head; they never create or drop it.
- Each test runs inside a DB transaction that's rolled back afterwards, so
  tests don't leak data into each other and don't need manual cleanup.
- The session joins that transaction with `join_transaction_mode="create_savepoint"`,
  so a `commit()` or `rollback()` inside a request handler acts on a
  SAVEPOINT instead of the test's outer transaction. Without it the
  handler's own transaction boundaries were invisible here: a rollback
  would tear down the test's transaction, and a commit would look like a
  no-op — which is precisely the blind spot that let a batch endpoint
  leave half its rows behind unnoticed.
- `client` overrides the app's `get_db` dependency to use that same
  per-test transaction, so requests made through the test client see
  exactly the data the test set up.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import rate_limit
from app.core.config import settings
from app.deps import get_db
from app.main import app


@pytest.fixture(scope="session")
def engine():
    if settings.test_database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    eng = create_engine(str(settings.test_database_url))
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine) -> Generator[Session, None, None]:
    connection = engine.connect()
    transaction = connection.begin()
    TestSessionLocal = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        # Makes the handler's commits and rollbacks observable without
        # letting them escape the test — see the module docstring.
        join_transaction_mode="create_savepoint",
    )
    session = TestSessionLocal()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()  # discards everything the test/request did
        connection.close()


@pytest.fixture(autouse=True)
def open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    # Production defaults to "approval", where a fresh account can't log in.
    # Most tests just need a usable user; the approval flow has its own file
    # that switches the mode back.
    monkeypatch.setattr(settings, "registration_mode", "open")


@pytest.fixture(autouse=True)
def no_email_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same idea as open_registration: most tests need a usable user, not the
    # confirmation step. test_email_flows.py switches it back on.
    monkeypatch.setattr(settings, "require_email_verification", False)


@pytest.fixture(autouse=True)
def fresh_rate_limits() -> None:
    # The counters are process-global; without this the many logins across
    # the suite would trip the limits that production relies on.
    rate_limit.reset()


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
        "accept_terms": True,
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
