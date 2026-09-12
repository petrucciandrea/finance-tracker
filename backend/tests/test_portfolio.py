"""
Tests for the portfolio router: holding CRUD, price caching, and net worth
(cash balances + holding market value, converted to the user's base currency).

External price/rate lookups are always monkeypatched — these tests never
hit Alpha Vantage, CoinGecko, or the real exchange-rate API.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def checking_account(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Main checking", "type": "checking", "currency": "EUR"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def investment_account(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Brokerage", "type": "investment", "currency": "USD"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def crypto_account(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Cold wallet", "type": "crypto_wallet", "currency": "USD"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(autouse=True)
def _mock_alpha_vantage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_from_alpha_vantage", lambda symbol: Decimal("150.00")
    )


@pytest.fixture(autouse=True)
def _mock_get_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same-currency conversions still short-circuit to 1 inside the real
    # get_rate — only patch it where a test needs a specific foreign rate.
    monkeypatch.setattr(
        "app.routers.portfolio.get_rate",
        lambda db, from_currency, to_currency, on_date: Decimal("1"),
    )


def _create_holding(
    client: TestClient,
    headers: dict,
    account_id: str,
    symbol: str = "AAPL",
    asset_type: str = "stock",
) -> dict:
    response = client.post(
        "/api/v1/portfolio/holdings",
        json={
            "account_id": account_id,
            "symbol": symbol,
            "asset_type": asset_type,
            "quantity": "10",
            "avg_buy_price": "140.00",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_holding_resolves_asset_and_caches_price(
    client: TestClient,
    registered_user: dict,
    investment_account: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_from_alpha_vantage",
        lambda symbol: calls.append(symbol) or Decimal("150.00"),
    )

    _create_holding(client, registered_user["auth_headers"], investment_account["id"])
    # First call (holding creation) + first GET both happen the same day —
    # the second GET should hit the DB cache, not the provider again.
    client.get("/api/v1/portfolio/holdings", headers=registered_user["auth_headers"])
    response = client.get("/api/v1/portfolio/holdings", headers=registered_user["auth_headers"])

    assert response.status_code == 200
    assert len(calls) == 1


def test_create_holding_rejects_checking_account(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    response = client.post(
        "/api/v1/portfolio/holdings",
        json={
            "account_id": checking_account["id"],
            "symbol": "AAPL",
            "asset_type": "stock",
            "quantity": "10",
            "avg_buy_price": "140.00",
        },
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 422


def test_create_holding_duplicate_returns_409(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    _create_holding(client, registered_user["auth_headers"], investment_account["id"])
    response = client.post(
        "/api/v1/portfolio/holdings",
        json={
            "account_id": investment_account["id"],
            "symbol": "AAPL",
            "asset_type": "stock",
            "quantity": "5",
            "avg_buy_price": "145.00",
        },
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 409


def test_list_holdings_computes_market_value_and_pnl(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    _create_holding(client, registered_user["auth_headers"], investment_account["id"])

    response = client.get("/api/v1/portfolio/holdings", headers=registered_user["auth_headers"])
    assert response.status_code == 200
    holding = response.json()[0]

    assert Decimal(holding["current_price"]) == Decimal("150.00")
    assert Decimal(holding["market_value"]) == Decimal("1500.00")
    # cost basis = 10 * 140 = 1400, market value = 1500 -> pnl = 100
    assert Decimal(holding["unrealized_pnl"]) == Decimal("100.00")
    assert holding["unrealized_pnl_percentage"] > 0


def test_update_holding_quantity(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    holding = _create_holding(client, registered_user["auth_headers"], investment_account["id"])

    response = client.patch(
        f"/api/v1/portfolio/holdings/{holding['id']}",
        json={"quantity": "20"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 200
    assert Decimal(response.json()["quantity"]) == Decimal("20")


def test_delete_holding_removes_it(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    holding = _create_holding(client, registered_user["auth_headers"], investment_account["id"])

    delete_response = client.delete(
        f"/api/v1/portfolio/holdings/{holding['id']}", headers=registered_user["auth_headers"]
    )
    assert delete_response.status_code == 204

    list_response = client.get(
        "/api/v1/portfolio/holdings", headers=registered_user["auth_headers"]
    )
    assert list_response.json() == []


def test_net_worth_includes_cash_and_holdings(
    client: TestClient, registered_user: dict, checking_account: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": checking_account["id"],
            "amount": "1000.00",
            "currency": "EUR",
            "date": "2026-09-01",
            "type": "income",
        },
        headers=headers,
    )
    _create_holding(client, headers, investment_account["id"])

    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert Decimal(body["total_cash_balance"]) == Decimal("1000.00")
    assert Decimal(body["total_holdings_value"]) == Decimal("1500.00")
    assert Decimal(body["total_net_worth"]) == Decimal("2500.00")


def test_net_worth_converts_foreign_currency_holdings(
    client: TestClient,
    registered_user: dict,
    investment_account: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.routers.portfolio.get_rate",
        lambda db, from_currency, to_currency, on_date: Decimal("0.90"),
    )
    headers = registered_user["auth_headers"]
    _create_holding(client, headers, investment_account["id"])

    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    body = response.json()

    # market_value (USD) 1500 * rate 0.90 -> 1350 in the user's EUR base currency
    assert Decimal(body["total_holdings_value"]) == Decimal("1350.00")
