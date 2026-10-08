"""Account erasure and export cover everything a user owns, and nothing else."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Base, User
from app.services.user_data import GLOBAL_TABLES, OWNED_TABLES

ME = "/api/v1/auth/me"


def test_every_table_is_either_owned_or_declared_global() -> None:
    # The guard: add a table without classifying it and erasure would leave its
    # rows behind after "delete my account".
    owned = {table for table, _ in OWNED_TABLES} | {"users"}

    assert owned.isdisjoint(GLOBAL_TABLES)
    assert owned | GLOBAL_TABLES == set(Base.metadata.tables)


def _seed(client: TestClient, headers: dict) -> dict:
    main = client.post(
        "/api/v1/accounts",
        json={
            "name": "Conto",
            "type": "checking",
            "currency": "EUR",
            "starting_balance": "1000.00",
        },
        headers=headers,
    ).json()
    savings = client.post(
        "/api/v1/accounts",
        json={"name": "Risparmi", "type": "savings", "currency": "EUR"},
        headers=headers,
    ).json()
    food = client.post(
        "/api/v1/categories", json={"name": "Cibo", "type": "expense"}, headers=headers
    ).json()
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": main["id"],
            "category_id": food["id"],
            "type": "expense",
            "amount": "-12.50",
            "currency": "EUR",
            "date": "2026-09-10",
            "description": "Pranzo",
        },
        headers=headers,
    )
    # A linked pair: the self-referencing counterpart FK is the tricky part.
    transfer = client.post(
        "/api/v1/transactions/transfers",
        json={
            "from_account_id": main["id"],
            "to_account_id": savings["id"],
            "amount": "300.00",
            "date": "2026-09-20",
        },
        headers=headers,
    )
    assert transfer.status_code == 201, transfer.text
    budget = client.post(
        "/api/v1/budgets",
        json={
            "category_id": food["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=headers,
    )
    assert budget.status_code == 201, budget.text
    goal = client.post(
        "/api/v1/planning/goals",
        json={"name": "PAC", "kind": "long_term", "priority": 2, "target_mode": "open_ended"},
        headers=headers,
    ).json()
    source = client.post(
        f"/api/v1/planning/goals/{goal['id']}/sources",
        json={"account_id": savings["id"]},
        headers=headers,
    )
    assert source.status_code == 201, source.text
    return {"main": main, "savings": savings}


def _count_for(db: Session, user_id: str) -> int:
    from app.services.user_data import OWNED_TABLES

    return sum(
        db.execute(text(f"SELECT count(*) FROM {t} WHERE {w}"), {"uid": user_id}).scalar_one()
        for t, w in OWNED_TABLES
    )


def test_delete_account_removes_everything_including_soft_deleted_rows(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    accounts = _seed(client, headers)
    # A soft-deleted row must go too: erasure overrides the soft-delete rule.
    client.delete(f"/api/v1/accounts/{accounts['savings']['id']}", headers=headers)
    uid = db_session.query(User).filter(User.email == registered_user["email"]).one().id
    assert _count_for(db_session, uid) > 0

    response = client.request(
        "DELETE", ME, json={"password": registered_user["password"]}, headers=headers
    )

    assert response.status_code == 204
    assert _count_for(db_session, uid) == 0
    assert db_session.query(User).filter(User.id == uid).count() == 0
    # And the account is really gone, not just emptied.
    assert client.get(ME, headers=headers).status_code == 401


def test_delete_account_with_wrong_password_changes_nothing(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    _seed(client, headers)

    response = client.request("DELETE", ME, json={"password": "nope-nope-nope"}, headers=headers)

    assert response.status_code == 403  # not 401: the client would refresh and retry
    assert client.get(ME, headers=headers).status_code == 200


def test_delete_account_leaves_other_users_data_alone(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "password123",
            "base_currency": "EUR",
            "accept_terms": True,
        },
    )
    assert other.status_code == 201
    tokens = client.post(
        "/api/v1/auth/login", json={"email": "other@example.com", "password": "password123"}
    ).json()
    other_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    _seed(client, other_headers)
    _seed(client, registered_user["auth_headers"])
    other_id = db_session.query(User).filter(User.email == "other@example.com").one().id
    before = _count_for(db_session, other_id)

    client.request(
        "DELETE",
        ME,
        json={"password": registered_user["password"]},
        headers=registered_user["auth_headers"],
    )

    assert _count_for(db_session, other_id) == before > 0


def test_delete_account_requires_authentication(client: TestClient) -> None:
    assert client.request("DELETE", ME, json={"password": "x"}).status_code == 401


def test_export_contains_the_users_data_and_no_secrets(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    _seed(client, headers)

    response = client.get(f"{ME}/export", headers=headers)

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    assert body["user"]["email"] == registered_user["email"]
    assert "password_hash" not in body["user"]
    assert "refresh_tokens" not in body["data"]
    assert {a["name"] for a in body["data"]["accounts"]} == {"Conto", "Risparmi"}
    assert any(t["description"] == "Pranzo" for t in body["data"]["transactions"])
    assert len(body["data"]["budgets"]) == 1
    # Money stays a string, not a float.
    amounts = [t["amount"] for t in body["data"]["transactions"]]
    assert all(isinstance(a, str) for a in amounts)
    assert Decimal("-12.50") in {Decimal(a) for a in amounts}


def test_export_does_not_include_other_users_data(
    client: TestClient, registered_user: dict
) -> None:
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "password123",
            "base_currency": "EUR",
            "accept_terms": True,
        },
    )
    tokens = client.post(
        "/api/v1/auth/login", json={"email": "other@example.com", "password": "password123"}
    ).json()
    _seed(client, {"Authorization": f"Bearer {tokens['access_token']}"})

    body = client.get(f"{ME}/export", headers=registered_user["auth_headers"]).json()

    assert body["data"]["accounts"] == []
    assert body["data"]["transactions"] == []


def test_export_requires_authentication(client: TestClient) -> None:
    assert client.get(f"{ME}/export").status_code == 401
