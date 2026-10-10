"""transfer_user copies one user, completely and faithfully, into another database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import Base
from app.services.user_data import OWNED_TABLES
from app.transfer_user import TransferError, copy_user
from tests.test_user_data import _seed

TARGET_DB = "ft_transfer_target"


@pytest.fixture
def target(engine, db_session: Session):
    """A second, empty database on the same server, torn down afterwards."""
    admin = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    admin.execute(text(f'DROP DATABASE IF EXISTS "{TARGET_DB}"'))
    admin.execute(text(f'CREATE DATABASE "{TARGET_DB}"'))
    target_engine = create_engine(engine.url.set(database=TARGET_DB))
    Base.metadata.create_all(target_engine)
    connection = target_engine.connect()
    transaction = connection.begin()
    # The currencies are reference data a migration seeds in real life.
    currencies = db_session.execute(text("SELECT * FROM currencies")).mappings().all()
    connection.execute(Base.metadata.tables["currencies"].insert(), [dict(c) for c in currencies])
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        target_engine.dispose()
        admin.execute(text(f'DROP DATABASE IF EXISTS "{TARGET_DB}"'))
        admin.close()


def _register(client: TestClient, email: str) -> dict:
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password123",
            "base_currency": "EUR",
            "accept_terms": True,
        },
    )
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "password123"}
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_copies_the_user_and_everything_they_own(
    client: TestClient, registered_user: dict, db_session: Session, target
) -> None:
    _seed(client, registered_user["auth_headers"])
    other = _register(client, "other@example.com")
    _seed(client, other)
    source = db_session.connection()

    report = copy_user(source, target, registered_user["email"], check_version=False)

    # Every table matches, and the user really had data in the interesting ones.
    assert all(src == dst for src, dst in report.values())
    for table in ("accounts", "transactions", "budgets", "categories", "savings_goals"):
        assert report[table][0] > 0, table
    # Exact copy of the account itself, password hash included.
    original = (
        source.execute(
            text("SELECT * FROM users WHERE email = :e"), {"e": registered_user["email"]}
        )
        .mappings()
        .one()
    )
    copied = (
        target.execute(
            text("SELECT * FROM users WHERE email = :e"), {"e": registered_user["email"]}
        )
        .mappings()
        .one()
    )
    assert dict(copied) == dict(original)
    # Nobody else came along, and sessions did not travel.
    assert _count(target, "users") == 1
    assert target.execute(text("SELECT count(*) FROM refresh_tokens")).scalar_one() == 0


def test_the_two_legs_of_a_transfer_keep_pointing_at_each_other(
    client: TestClient, registered_user: dict, db_session: Session, target
) -> None:
    _seed(client, registered_user["auth_headers"])  # creates a linked giroconto

    copy_user(db_session.connection(), target, registered_user["email"], check_version=False)

    pairs = target.execute(
        text(
            "SELECT count(*) FROM transactions a JOIN transactions b "
            "ON a.counterpart_transaction_id = b.id AND b.counterpart_transaction_id = a.id"
        )
    ).scalar_one()
    assert pairs == 2  # each leg sees the other


def test_every_registered_table_ends_up_with_the_same_rows(
    client: TestClient, registered_user: dict, db_session: Session, target
) -> None:
    _seed(client, registered_user["auth_headers"])

    report = copy_user(
        db_session.connection(), target, registered_user["email"], check_version=False
    )

    skipped = {"refresh_tokens"}
    assert {name for name, _ in OWNED_TABLES} - skipped <= set(report)


def test_refuses_to_overwrite_a_user_that_already_exists(
    client: TestClient, registered_user: dict, db_session: Session, target
) -> None:
    source = db_session.connection()
    copy_user(source, target, registered_user["email"], check_version=False)

    with pytest.raises(TransferError, match="already exists"):
        copy_user(source, target, registered_user["email"], check_version=False)


def test_unknown_user_is_a_clear_error(db_session: Session, target) -> None:
    with pytest.raises(TransferError, match="No user"):
        copy_user(db_session.connection(), target, "nobody@example.com", check_version=False)


def test_a_target_at_another_revision_is_refused(
    registered_user: dict, db_session: Session, target
) -> None:
    target.execute(text("CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)"))
    target.execute(text("INSERT INTO alembic_version VALUES ('an-older-revision')"))

    with pytest.raises(TransferError, match="different Alembic revisions"):
        copy_user(db_session.connection(), target, registered_user["email"])

    assert _count(target, "users") == 0  # refused before writing anything
