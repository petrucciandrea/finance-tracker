"""
Tests for the accounts router, focused on the `starting_balance` option on
creation: it should produce an opening-balance transaction (type=transfer,
so it never counts toward a budget or forces a "Varie" category) rather
than a separate stored balance field.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


def test_create_account_without_starting_balance_creates_no_transaction(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Main checking", "type": "checking", "currency": "EUR"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text

    transactions = client.get(
        "/api/v1/transactions", headers=registered_user["auth_headers"]
    ).json()
    assert transactions["meta"]["total_items"] == 0


def test_create_account_with_starting_balance_creates_opening_transaction(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Main checking",
            "type": "checking",
            "currency": "EUR",
            "starting_balance": "1000.00",
        },
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    account = response.json()

    transactions = client.get(
        "/api/v1/transactions", headers=registered_user["auth_headers"]
    ).json()["data"]
    assert len(transactions) == 1
    opening = transactions[0]
    assert opening["account_id"] == account["id"]
    assert opening["type"] == "transfer"
    assert opening["category_id"] is None
    assert Decimal(opening["amount"]) == Decimal("1000.00")
    assert Decimal(opening["amount_base_currency"]) == Decimal("1000.00")


def test_create_account_with_negative_starting_balance(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Credit card",
            "type": "credit_card",
            "currency": "EUR",
            "starting_balance": "-250.00",
        },
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text

    transactions = client.get(
        "/api/v1/transactions", headers=registered_user["auth_headers"]
    ).json()["data"]
    assert Decimal(transactions[0]["amount"]) == Decimal("-250.00")


def test_create_account_with_zero_starting_balance_creates_no_transaction(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Main checking",
            "type": "checking",
            "currency": "EUR",
            "starting_balance": "0",
        },
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text

    transactions = client.get(
        "/api/v1/transactions", headers=registered_user["auth_headers"]
    ).json()
    assert transactions["meta"]["total_items"] == 0


def test_starting_balance_uses_mocked_rate_for_foreign_currency(
    client: TestClient, registered_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.routers.accounts.get_rate",
        lambda db, from_currency, to_currency, on_date: Decimal("0.90"),
    )

    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "US brokerage cash",
            "type": "investment",
            "currency": "USD",
            "starting_balance": "100.00",
        },
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text

    transactions = client.get(
        "/api/v1/transactions", headers=registered_user["auth_headers"]
    ).json()["data"]
    assert Decimal(transactions[0]["amount_base_currency"]) == Decimal("90.00")


def test_cash_account_counts_toward_net_worth(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Portafoglio",
            "type": "cash",
            "currency": "EUR",
            "starting_balance": "80.00",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["type"] == "cash"

    net_worth = client.get("/api/v1/portfolio/net-worth", headers=headers)
    assert net_worth.status_code == 200, net_worth.text
    assert Decimal(net_worth.json()["total_cash_balance"]) == Decimal("80.00")
