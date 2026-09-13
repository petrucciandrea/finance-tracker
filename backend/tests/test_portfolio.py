"""
Tests for the portfolio router: asset transaction (buy/sell) CRUD, the
weighted-average-cost holdings computed from them, price caching, and net
worth (cash balances + holding market value, converted to the user's base
currency).

External price/rate lookups are always monkeypatched — these tests never
hit Yahoo Finance, CoinGecko, or the real exchange-rate API.
"""

from datetime import date
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
def _mock_yahoo_finance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_from_yahoo_finance", lambda symbol: Decimal("150.00")
    )
    # Investment accounts in these tests are USD, so assets resolving to USD
    # keeps `get_rate` short-circuiting to 1 without needing per-test mocks.
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_currency_from_yahoo_finance", lambda symbol: "USD"
    )


@pytest.fixture(autouse=True)
def _mock_get_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same-currency conversions still short-circuit to 1 inside the real
    # get_rate — only patch it where a test needs a specific foreign rate.
    monkeypatch.setattr(
        "app.routers.portfolio.get_rate",
        lambda db, from_currency, to_currency, on_date: Decimal("1"),
    )


def _create_asset_transaction(
    client: TestClient,
    headers: dict,
    account_id: str,
    symbol: str = "AAPL",
    asset_type: str = "stock",
    type_: str = "buy",
    quantity: str = "10",
    price: str = "140.00",
    fee: str = "0",
    date: str = "2026-09-01",
    notes: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": account_id,
            "symbol": symbol,
            "asset_type": asset_type,
            "type": type_,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "date": date,
            "notes": notes,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_buy_resolves_asset_and_caches_price(
    client: TestClient,
    registered_user: dict,
    investment_account: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_from_yahoo_finance",
        lambda symbol: calls.append(symbol) or Decimal("150.00"),
    )

    _create_asset_transaction(client, registered_user["auth_headers"], investment_account["id"])
    # First call (transaction creation) + first GET both happen the same day
    # — the second GET should hit the DB cache, not the provider again.
    client.get("/api/v1/portfolio/holdings", headers=registered_user["auth_headers"])
    response = client.get("/api/v1/portfolio/holdings", headers=registered_user["auth_headers"])

    assert response.status_code == 200
    assert len(calls) == 1


def test_create_transaction_rejects_checking_account(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": checking_account["id"],
            "symbol": "AAPL",
            "asset_type": "stock",
            "type": "buy",
            "quantity": "10",
            "price": "140.00",
            "date": "2026-09-01",
        },
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 422


def test_list_holdings_computes_weighted_average_and_pnl(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    account_id = investment_account["id"]
    _create_asset_transaction(client, headers, account_id, quantity="10", price="100.00")
    _create_asset_transaction(client, headers, account_id, quantity="10", price="200.00")

    response = client.get("/api/v1/portfolio/holdings", headers=headers)
    assert response.status_code == 200
    holding = response.json()[0]

    # weighted average of 10@100 + 10@200 = (1000+2000)/20 = 150
    assert Decimal(holding["quantity"]) == Decimal("20")
    assert Decimal(holding["avg_buy_price"]) == Decimal("150.00")
    assert Decimal(holding["current_price"]) == Decimal("150.00")
    assert Decimal(holding["market_value"]) == Decimal("3000.00")
    # cost basis 3000, market value 3000 -> no unrealized pnl
    assert Decimal(holding["unrealized_pnl"]) == Decimal("0.00")
    assert Decimal(holding["realized_pnl"]) == Decimal("0")


def test_sell_reduces_quantity_and_computes_realized_pnl(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    account_id = investment_account["id"]
    _create_asset_transaction(client, headers, account_id, quantity="10", price="100.00")
    _create_asset_transaction(
        client, headers, account_id, type_="sell", quantity="4", price="150.00"
    )

    response = client.get("/api/v1/portfolio/holdings", headers=headers)
    holding = response.json()[0]

    assert Decimal(holding["quantity"]) == Decimal("6")
    assert Decimal(holding["avg_buy_price"]) == Decimal("100.00")
    # realized pnl = (150 - 100) * 4 = 200
    assert Decimal(holding["realized_pnl"]) == Decimal("200.00")


def test_oversell_is_rejected(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    account_id = investment_account["id"]
    _create_asset_transaction(client, headers, account_id, quantity="5", price="100.00")

    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": account_id,
            "symbol": "AAPL",
            "asset_type": "stock",
            "type": "sell",
            "quantity": "10",
            "price": "150.00",
            "date": "2026-09-02",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_update_transaction_quantity_recomputes_amount(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    transaction = _create_asset_transaction(
        client, headers, investment_account["id"], quantity="10", price="100.00"
    )
    assert Decimal(transaction["amount_base_currency"]) == Decimal("1000.00")

    response = client.patch(
        f"/api/v1/portfolio/transactions/{transaction['id']}",
        json={"quantity": "20"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["quantity"]) == Decimal("20")
    assert Decimal(body["amount_base_currency"]) == Decimal("2000.00")


def test_update_transaction_notes_only_does_not_recompute(
    client: TestClient,
    registered_user: dict,
    investment_account: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = registered_user["auth_headers"]
    transaction = _create_asset_transaction(client, headers, investment_account["id"])

    calls = []
    monkeypatch.setattr(
        "app.routers.portfolio.get_rate",
        lambda db, from_currency, to_currency, on_date: calls.append(1) or Decimal("1"),
    )
    response = client.patch(
        f"/api/v1/portfolio/transactions/{transaction['id']}",
        json={"notes": "just a note"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["amount_base_currency"] == transaction["amount_base_currency"]
    assert calls == []


def test_update_sell_quantity_still_validates_overdraw(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    account_id = investment_account["id"]
    _create_asset_transaction(client, headers, account_id, quantity="10", price="100.00")
    sell = _create_asset_transaction(
        client, headers, account_id, type_="sell", quantity="4", price="150.00"
    )

    response = client.patch(
        f"/api/v1/portfolio/transactions/{sell['id']}",
        json={"quantity": "20"},
        headers=headers,
    )
    assert response.status_code == 422


def test_delete_transaction_soft_deletes_and_removes_holding(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    transaction = _create_asset_transaction(client, headers, investment_account["id"])

    delete_response = client.delete(
        f"/api/v1/portfolio/transactions/{transaction['id']}", headers=headers
    )
    assert delete_response.status_code == 204

    list_response = client.get("/api/v1/portfolio/holdings", headers=headers)
    assert list_response.json() == []

    transactions_response = client.get("/api/v1/portfolio/transactions", headers=headers)
    assert transactions_response.json() == []


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
    _create_asset_transaction(client, headers, investment_account["id"])

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
    _create_asset_transaction(client, headers, investment_account["id"])

    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    body = response.json()

    # market_value (USD) 1500 * rate 0.90 -> 1350 in the user's EUR base currency
    assert Decimal(body["total_holdings_value"]) == Decimal("1350.00")


def test_portfolio_history_returns_points(
    client: TestClient,
    registered_user: dict,
    investment_account: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.routers.portfolio.asset_prices_service.get_price_history",
        lambda db, asset, start_date, end_date: {},
    )
    monkeypatch.setattr(
        "app.routers.portfolio.get_rate_history",
        lambda db, from_currency, to_currency, start_date, end_date: {},
    )
    headers = registered_user["auth_headers"]
    _create_asset_transaction(client, headers, investment_account["id"])

    response = client.get("/api/v1/portfolio/history?period=1m", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["base_currency"] == "EUR"
    assert len(body["points"]) > 0
    assert body["points"][-1]["date"] == date.today().isoformat()
