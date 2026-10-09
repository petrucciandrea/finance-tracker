"""Retention removes what is no longer needed, and only that."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Account, Category, Transaction, User
from app.models.refresh_token import RefreshToken
from app.services import retention

LATER = timedelta(days=120)  # past every retention window


def _later() -> datetime:
    return datetime.now(UTC) + LATER


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def _account(client: TestClient, headers: dict, name: str = "Conto") -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": "checking", "currency": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _expense(client: TestClient, headers: dict, account_id: str, **extra) -> dict:
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "type": "expense",
            "amount": "-10.00",
            "currency": "EUR",
            "date": "2026-09-10",
            **extra,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- refresh tokens -----------------------------------------------------------


def test_old_expired_or_revoked_tokens_go_and_live_ones_stay(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    # registered_user holds one live token. Add an expired one and a revoked one.
    user = db_session.query(User).filter(User.email == registered_user["email"]).one()
    now = datetime.now(UTC)
    db_session.add_all(
        [
            RefreshToken(
                user_id=user.id, token_hash="expired", expires_at=now - timedelta(days=30)
            ),
            RefreshToken(
                user_id=user.id,
                token_hash="revoked",
                expires_at=now + timedelta(days=20),
                revoked_at=now - timedelta(days=30),
            ),
        ]
    )
    db_session.flush()

    report = retention.purge(db_session)

    assert report["refresh_tokens"] == 2
    assert db_session.query(RefreshToken).filter_by(user_id=user.id).count() == 1


def test_recently_revoked_tokens_are_kept_for_a_while(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    client.post("/api/v1/auth/logout", json={"refresh_token": registered_user["refresh_token"]})

    assert retention.purge(db_session)["refresh_tokens"] == 0


# --- soft-deleted rows ---------------------------------------------------------


def test_soft_deleted_rows_are_kept_inside_the_window_and_purged_after(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    gone = _expense(client, headers, account["id"], description="to delete")
    _expense(client, headers, account["id"], description="to keep")
    client.delete(f"/api/v1/transactions/{gone['id']}", headers=headers)

    assert "transactions" not in retention.purge(db_session)
    report = retention.purge(db_session, now=_later())

    assert report["transactions"] == 1
    remaining = db_session.query(Transaction).filter(Transaction.account_id == account["id"])
    assert [t.description for t in remaining] == ["to keep"]  # live rows never touched


def test_a_deleted_account_still_referenced_by_live_transactions_is_kept(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    # History renders "deleted" off that FK on purpose; purging it would break or erase it.
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    _expense(client, headers, account["id"])
    client.delete(f"/api/v1/accounts/{account['id']}", headers=headers)

    retention.purge(db_session, now=_later())

    assert db_session.get(Account, account["id"]) is not None
    assert db_session.query(Transaction).filter_by(account_id=account["id"]).count() == 1


def test_a_deleted_account_goes_once_nothing_references_it(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    tx = _expense(client, headers, account["id"])
    client.delete(f"/api/v1/transactions/{tx['id']}", headers=headers)
    client.delete(f"/api/v1/accounts/{account['id']}", headers=headers)

    report = retention.purge(db_session, now=_later())

    # The transaction goes first, which frees the account in the same run.
    assert report["transactions"] == 1
    assert report["accounts"] == 1
    assert db_session.get(Account, account["id"]) is None


def test_both_legs_of_a_deleted_transfer_are_purged_together(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    # The legs point at each other, so each would block the other's removal.
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")
    legs = client.post(
        "/api/v1/transactions/transfers",
        json={
            "from_account_id": main["id"],
            "to_account_id": savings["id"],
            "amount": "50.00",
            "date": "2026-09-20",
        },
        headers=headers,
    ).json()
    client.delete(f"/api/v1/transactions/{legs[0]['id']}", headers=headers)

    report = retention.purge(db_session, now=_later())

    assert report["transactions"] == 2


def test_a_deleted_category_with_live_transactions_is_kept(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    category = client.post(
        "/api/v1/categories", json={"name": "Cibo", "type": "expense"}, headers=headers
    ).json()
    _expense(client, headers, account["id"], category_id=category["id"])
    client.delete(f"/api/v1/categories/{category['id']}", headers=headers)

    retention.purge(db_session, now=_later())

    assert db_session.get(Category, category["id"]) is not None


# --- accounts that never finished signing up -------------------------------------


def _user(db: Session, email: str, **fields) -> User:
    user = User(email=email, password_hash="x", base_currency="EUR", **fields)
    db.add(user)
    db.flush()
    return user


def test_rejected_and_never_confirmed_accounts_are_purged_after_their_windows(
    client: TestClient, db_session: Session
) -> None:
    now = datetime.now(UTC)
    _user(db_session, "rejected@example.com", approval_status="rejected")
    _user(db_session, "unconfirmed@example.com", email_verified_at=None)
    _user(db_session, "pending@example.com", approval_status="pending")
    _user(db_session, "fine@example.com", email_verified_at=now)

    assert retention.purge(db_session)["rejected_users"] == 0  # too recent
    report = retention.purge(db_session, now=_later())

    assert report["rejected_users"] == 1
    assert report["unverified_users"] == 1
    emails = {u.email for u in db_session.query(User)}
    assert "pending@example.com" in emails  # still waiting on the admin
    assert "fine@example.com" in emails
    assert not emails & {"rejected@example.com", "unconfirmed@example.com"}


def test_purge_does_not_touch_other_users_live_data(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    _expense(client, headers, account["id"])
    before = db_session.scalar(text("select count(*) from transactions"))

    retention.purge(db_session, now=_later())

    assert db_session.scalar(text("select count(*) from transactions")) == before
    assert _count(db_session, Account) >= 1


def test_the_cli_dry_run_reports_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, capsys
) -> None:
    from app import purge

    _user(db_session, "rejected@example.com", approval_status="rejected")
    db_session.query(User).filter_by(email="rejected@example.com").update(
        {"created_at": datetime.now(UTC) - LATER}
    )
    # Commit (to the test's savepoint) so the dry run's rollback can only undo
    # the purge, not the setup above.
    db_session.commit()
    monkeypatch.setattr(purge, "SessionLocal", lambda: _Borrowed(db_session))

    purge.main(["--dry-run"])

    assert "would remove 1 row(s)" in capsys.readouterr().out
    assert db_session.query(User).filter_by(email="rejected@example.com").count() == 1


class _Borrowed:
    """Lets the CLI use the test's session without closing it."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *exc) -> None:
        return None
