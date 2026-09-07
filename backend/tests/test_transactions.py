"""
Tests for the transactions router: creation with currency conversion,
listing/filtering, summary aggregation, and soft delete.

The exchange rate lookup is monkeypatched everywhere a cross-currency
transaction is created, so these tests never hit the real Frankfurter API —
keeps them fast and deterministic regardless of network access.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def eur_account(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Main checking", "type": "checking", "currency": "EUR"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def food_category(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/categories",
        json={"name": "Food", "type": "expense"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_transaction_same_currency_uses_rate_one(
    client: TestClient, registered_user: dict, eur_account: dict, food_category: dict
) -> None:
    # Account and user base_currency are both EUR — get_rate short-circuits
    # to 1 without any network call, so no mocking needed here.
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "category_id": food_category["id"],
            "amount": "-42.50",
            "currency": "EUR",
            "date": "2026-08-15",
            "description": "Groceries",
            "type": "expense",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["amount_base_currency"]) == Decimal("-42.50")
    assert Decimal(body["exchange_rate"]) == Decimal("1")


def test_create_transaction_cross_currency_uses_mocked_rate(
    client: TestClient,
    registered_user: dict,
    eur_account: dict,
    food_category: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.routers.transactions.get_rate",
        lambda db, from_currency, to_currency, on_date: Decimal("0.92"),
    )

    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "category_id": food_category["id"],
            "amount": "-100.00",
            "currency": "USD",
            "date": "2026-08-15",
            "description": "Hotel in the US",
            "type": "expense",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["exchange_rate"]) == Decimal("0.92")
    assert Decimal(body["amount_base_currency"]) == Decimal("-92.00")


def test_create_transaction_rejects_account_owned_by_another_user(
    client: TestClient, registered_user: dict, eur_account: dict
) -> None:
    # Second, unrelated user must not be able to post against the first
    # user's account — this is the ownership check in _get_owned_account_or_404.
    other_user = client.post(
        "/api/v1/auth/register",
        json={"email": "other.user@example.com", "password": "password123", "base_currency": "EUR"},
    )
    assert other_user.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "other.user@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "amount": "-10.00",
            "currency": "EUR",
            "date": "2026-08-15",
            "type": "expense",
        },
        headers=other_headers,
    )

    assert response.status_code == 404


def test_list_transactions_filters_by_category(
    client: TestClient, registered_user: dict, eur_account: dict, food_category: dict
) -> None:
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "category_id": food_category["id"],
            "amount": "-20.00",
            "currency": "EUR",
            "date": "2026-08-01",
            "type": "expense",
        },
        headers=registered_user["auth_headers"],
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "category_id": None,
            "amount": "-5.00",
            "currency": "EUR",
            "date": "2026-08-02",
            "type": "expense",
        },
        headers=registered_user["auth_headers"],
    )

    response = client.get(
        "/api/v1/transactions",
        params={"category_id": food_category["id"]},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total_items"] == 1
    assert body["data"][0]["category_id"] == food_category["id"]


def test_summary_grouped_by_category_and_month(
    client: TestClient, registered_user: dict, eur_account: dict, food_category: dict
) -> None:
    for amount, txn_date in [("-20.00", "2026-08-01"), ("-30.00", "2026-08-20")]:
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": eur_account["id"],
                "category_id": food_category["id"],
                "amount": amount,
                "currency": "EUR",
                "date": txn_date,
                "type": "expense",
            },
            headers=registered_user["auth_headers"],
        )

    response = client.get(
        "/api/v1/transactions/summary",
        params={"group_by": ["category", "month"]},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) == 1  # both transactions fall in the same month+category
    assert items[0]["month"] == "2026-08"
    assert items[0]["category_id"] == food_category["id"]
    assert Decimal(items[0]["total_amount_base_currency"]) == Decimal("-50.00")
    assert items[0]["transaction_count"] == 2


def test_delete_transaction_is_soft_delete(
    client: TestClient, registered_user: dict, eur_account: dict
) -> None:
    create_response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "amount": "-15.00",
            "currency": "EUR",
            "date": "2026-08-10",
            "type": "expense",
        },
        headers=registered_user["auth_headers"],
    )
    transaction_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/transactions/{transaction_id}", headers=registered_user["auth_headers"]
    )
    assert delete_response.status_code == 204

    # Soft-deleted: a direct GET now 404s (filtered out), and it disappears
    # from the list — but the row itself is never physically removed.
    get_response = client.get(
        f"/api/v1/transactions/{transaction_id}", headers=registered_user["auth_headers"]
    )
    assert get_response.status_code == 404

    list_response = client.get("/api/v1/transactions", headers=registered_user["auth_headers"])
    ids = [t["id"] for t in list_response.json()["data"]]
    assert transaction_id not in ids
