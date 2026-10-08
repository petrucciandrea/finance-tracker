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
    #
    # Two patch targets because monkeypatch binds to the import site, and
    # there are two: the router converts a buy/sell's cash leg, while
    # holding valuation moved into services/net_worth.py when the planning
    # engine started needing the same balances.
    for target in ("app.routers.portfolio.get_rate", "app.services.net_worth.get_rate"):
        monkeypatch.setattr(
            target, lambda db, from_currency, to_currency, on_date: Decimal("1")
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


def test_update_buy_quantity_cannot_drop_below_what_was_sold(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    account_id = investment_account["id"]
    buy = _create_asset_transaction(client, headers, account_id, quantity="10", price="100.00")
    _create_asset_transaction(
        client, headers, account_id, type_="sell", quantity="4", price="150.00"
    )

    response = client.patch(
        f"/api/v1/portfolio/transactions/{buy['id']}", json={"quantity": "3"}, headers=headers
    )
    assert response.status_code == 422

    response = client.patch(
        f"/api/v1/portfolio/transactions/{buy['id']}", json={"quantity": "4"}, headers=headers
    )
    assert response.status_code == 200


def test_delete_buy_refused_when_a_sell_relies_on_it(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    account_id = investment_account["id"]
    buy = _create_asset_transaction(client, headers, account_id, quantity="10", price="100.00")
    sell = _create_asset_transaction(
        client, headers, account_id, type_="sell", quantity="4", price="150.00"
    )

    buy_url = f"/api/v1/portfolio/transactions/{buy['id']}"
    sell_url = f"/api/v1/portfolio/transactions/{sell['id']}"
    assert client.delete(buy_url, headers=headers).status_code == 422

    # Retire the sell first and the buy goes.
    assert client.delete(sell_url, headers=headers).status_code == 204
    assert client.delete(buy_url, headers=headers).status_code == 204


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
    client: TestClient,
    registered_user: dict,
    checking_account: dict,
    investment_account: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This test now also posts a manual USD deposit through /transactions
    # (not just /portfolio/transactions), which has its own get_rate import —
    # the autouse _mock_get_rate fixture only patches the portfolio router's.
    monkeypatch.setattr(
        "app.routers.transactions.get_rate",
        lambda db, from_currency, to_currency, on_date: Decimal("1"),
    )
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
    # Fund the investment account before buying — a buy deducts its cost
    # from the account's cash (see test_buy_deducts_cost_from_account_cash),
    # so without this deposit the purchase would just drive that account's
    # cash negative rather than actually converting cash into a holding.
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": investment_account["id"],
            "amount": "1400.00",
            "currency": "USD",
            "date": "2026-09-01",
            "type": "transfer",
        },
        headers=headers,
    )
    _create_asset_transaction(client, headers, investment_account["id"])

    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    assert response.status_code == 200
    body = response.json()

    # Investment account cash: +1400 deposit, -1400 spent on the buy -> 0.
    # Checking cash (1000) is the only cash left, holdings are worth 1500
    # (mocked at $150/share) — if the buy's cost weren't deducted from cash,
    # this would double-count the 1400 spent as both still-there cash AND
    # holdings value.
    assert Decimal(body["total_cash_balance"]) == Decimal("1000.00")
    assert Decimal(body["total_holdings_value"]) == Decimal("1500.00")
    assert Decimal(body["total_net_worth"]) == Decimal("2500.00")


def test_buy_deducts_cost_from_account_cash(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": investment_account["id"],
            "amount": "2000.00",
            "currency": "USD",
            "date": "2026-09-01",
            "type": "transfer",
        },
        headers=headers,
    )
    _create_asset_transaction(client, headers, investment_account["id"])  # 10 x $140 = $1400

    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    accounts = response.json()["accounts"]
    investment_balance = next(a for a in accounts if a["account_id"] == investment_account["id"])
    assert Decimal(investment_balance["balance"]) == Decimal("600.00")


def test_buy_records_a_transfer_transaction_not_an_expense(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    _create_asset_transaction(client, registered_user["auth_headers"], investment_account["id"])

    response = client.get(
        "/api/v1/transactions", params={"account_id": investment_account["id"]}, headers=headers
    )
    transactions = response.json()["data"]
    assert len(transactions) == 1
    assert transactions[0]["type"] == "transfer"
    assert transactions[0]["category_id"] is None
    assert Decimal(transactions[0]["amount"]) == Decimal("-1400.00")


def test_sell_credits_account_cash(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    _create_asset_transaction(
        client, headers, investment_account["id"], quantity="10", price="140.00"
    )
    _create_asset_transaction(
        client, headers, investment_account["id"], type_="sell", quantity="4", price="150.00"
    )

    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    accounts = response.json()["accounts"]
    investment_balance = next(a for a in accounts if a["account_id"] == investment_account["id"])
    # -1400 (buy) + 600 (sell 4 @ 150) = -800
    assert Decimal(investment_balance["balance"]) == Decimal("-800.00")


def test_delete_asset_transaction_reverses_its_cash_transaction(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    created = _create_asset_transaction(client, headers, investment_account["id"])

    delete_response = client.delete(
        f"/api/v1/portfolio/transactions/{created['id']}", headers=headers
    )
    assert delete_response.status_code == 204

    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    accounts = response.json()["accounts"]
    investment_balance = next(a for a in accounts if a["account_id"] == investment_account["id"])
    assert Decimal(investment_balance["balance"]) == Decimal("0")


def test_update_asset_transaction_quantity_updates_linked_cash_transaction(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    created = _create_asset_transaction(
        client, headers, investment_account["id"], quantity="10", price="140.00"
    )

    update_response = client.patch(
        f"/api/v1/portfolio/transactions/{created['id']}", json={"quantity": "5"}, headers=headers
    )
    assert update_response.status_code == 200

    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    accounts = response.json()["accounts"]
    investment_balance = next(a for a in accounts if a["account_id"] == investment_account["id"])
    assert Decimal(investment_balance["balance"]) == Decimal("-700.00")


def test_can_categorize_the_linked_cash_transaction_but_not_edit_its_amount_or_delete_it(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    _create_asset_transaction(client, headers, investment_account["id"])
    transfer_category = client.post(
        "/api/v1/categories",
        json={"name": "Investimenti", "type": "transfer"},
        headers=headers,
    ).json()

    list_response = client.get(
        "/api/v1/transactions", params={"account_id": investment_account["id"]}, headers=headers
    )
    cash_transaction_id = list_response.json()["data"][0]["id"]

    # category_id/description don't feed into the cash math, so they're free
    # to edit — e.g. tagging every buy/sell with an "Investimenti" category.
    recategorize_response = client.patch(
        f"/api/v1/transactions/{cash_transaction_id}",
        json={"category_id": transfer_category["id"], "description": "edited"},
        headers=headers,
    )
    assert recategorize_response.status_code == 200
    assert recategorize_response.json()["category_id"] == transfer_category["id"]

    # amount/date, however, must stay in lockstep with the asset transaction.
    amount_edit_response = client.patch(
        f"/api/v1/transactions/{cash_transaction_id}",
        json={"amount": "-1.00"},
        headers=headers,
    )
    assert amount_edit_response.status_code == 409

    delete_response = client.delete(
        f"/api/v1/transactions/{cash_transaction_id}", headers=headers
    )
    assert delete_response.status_code == 409


def test_net_worth_converts_foreign_currency_holdings(
    client: TestClient,
    registered_user: dict,
    investment_account: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Holding valuation, so the net_worth service is the import site here.
    monkeypatch.setattr(
        "app.services.net_worth.get_rate",
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


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

def _upload_asset_csv(client: TestClient, headers: dict, account_id: str, csv_text: str) -> dict:
    response = client.post(
        "/api/v1/portfolio/transactions/import",
        params={"account_id": account_id},
        files={"file": ("transactions.csv", csv_text.encode("utf-8"), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_asset_import_preview_flags_invalid_and_valid_rows(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    csv_text = (
        "symbol,asset_type,type,quantity,price,fee,date,notes\n"
        "AAPL,stock,buy,10,140.00,0,2026-09-01,first buy\n"
        "AAPL,stock,sell,not-a-number,150.00,0,2026-09-05,bad quantity\n"
    )
    preview = _upload_asset_csv(
        client, registered_user["auth_headers"], investment_account["id"], csv_text
    )

    assert preview["total_rows"] == 2
    assert preview["parsable_rows"] == 1
    assert preview["rows"][0]["is_parsable"] is True
    assert preview["rows"][1]["is_parsable"] is False
    assert preview["rows"][1]["error"] is not None


def test_asset_import_preview_flags_duplicates(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    _create_asset_transaction(
        client, headers, investment_account["id"], quantity="10", price="140.00", date="2026-09-01"
    )

    csv_text = (
        "symbol,asset_type,type,quantity,price,fee,date,notes\n"
        "AAPL,stock,buy,10,140.00,0,2026-09-01,\n"
    )
    preview = _upload_asset_csv(client, headers, investment_account["id"], csv_text)

    assert preview["duplicate_rows"] == 1
    assert preview["rows"][0]["is_duplicate"] is True


def test_asset_import_rejects_checking_account(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    csv_text = (
        "symbol,asset_type,type,quantity,price,fee,date,notes\n"
        "AAPL,stock,buy,10,140.00,0,2026-09-01,\n"
    )
    response = client.post(
        "/api/v1/portfolio/transactions/import",
        params={"account_id": checking_account["id"]},
        files={"file": ("t.csv", csv_text.encode("utf-8"), "text/csv")},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 422


def test_asset_import_confirm_creates_transactions_and_computes_holdings(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    csv_text = (
        "symbol,asset_type,type,quantity,price,fee,date,notes\n"
        "AAPL,stock,buy,10,100.00,0,2026-09-01,opening buy\n"
        "AAPL,stock,buy,10,200.00,0,2026-09-02,second buy\n"
    )
    preview = _upload_asset_csv(client, headers, investment_account["id"], csv_text)
    row_numbers = [r["row_number"] for r in preview["rows"]]

    confirm_response = client.post(
        "/api/v1/portfolio/transactions/import/confirm",
        json={"import_id": preview["import_id"], "row_numbers": row_numbers},
        headers=headers,
    )
    assert confirm_response.status_code == 200
    created = confirm_response.json()
    assert len(created) == 2

    holdings_response = client.get("/api/v1/portfolio/holdings", headers=headers)
    holding = holdings_response.json()[0]
    # weighted average of 10@100 + 10@200 = 150
    assert Decimal(holding["avg_buy_price"]) == Decimal("150.00")
    assert Decimal(holding["quantity"]) == Decimal("20")


def test_asset_import_confirm_processes_buy_before_sell_on_tied_date(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    """
    A same-day sell of a symbol first bought in this same CSV must not be
    treated as an overdraw just because of row order in the file.
    """
    headers = registered_user["auth_headers"]
    csv_text = (
        "symbol,asset_type,type,quantity,price,fee,date,notes\n"
        "AAPL,stock,sell,4,150.00,0,2026-09-01,sell listed first in the file\n"
        "AAPL,stock,buy,10,100.00,0,2026-09-01,buy listed second\n"
    )
    preview = _upload_asset_csv(client, headers, investment_account["id"], csv_text)
    row_numbers = [r["row_number"] for r in preview["rows"]]

    confirm_response = client.post(
        "/api/v1/portfolio/transactions/import/confirm",
        json={"import_id": preview["import_id"], "row_numbers": row_numbers},
        headers=headers,
    )
    assert confirm_response.status_code == 200
    assert len(confirm_response.json()) == 2

    holdings_response = client.get("/api/v1/portfolio/holdings", headers=headers)
    holding = holdings_response.json()[0]
    assert Decimal(holding["quantity"]) == Decimal("6")
    assert Decimal(holding["realized_pnl"]) == Decimal("200.00")


def test_asset_import_confirm_skips_row_that_would_overdraw(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    csv_text = (
        "symbol,asset_type,type,quantity,price,fee,date,notes\n"
        "AAPL,stock,sell,999,150.00,0,2026-09-01,no prior position\n"
    )
    preview = _upload_asset_csv(client, headers, investment_account["id"], csv_text)
    row_numbers = [r["row_number"] for r in preview["rows"]]

    confirm_response = client.post(
        "/api/v1/portfolio/transactions/import/confirm",
        json={"import_id": preview["import_id"], "row_numbers": row_numbers},
        headers=headers,
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json() == []

    holdings_response = client.get("/api/v1/portfolio/holdings", headers=headers)
    assert holdings_response.json() == []


def test_buy_files_its_cash_leg_under_the_given_transfer_category(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    category = client.post(
        "/api/v1/categories", json={"name": "Investimenti", "type": "transfer"}, headers=headers
    ).json()

    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": investment_account["id"],
            "symbol": "AAPL",
            "asset_type": "stock",
            "type": "buy",
            "quantity": "10",
            "price": "140.00",
            "date": "2026-09-01",
            "category_id": category["id"],
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    (cash,) = client.get(
        "/api/v1/transactions", params={"account_id": investment_account["id"]}, headers=headers
    ).json()["data"]
    assert cash["category_id"] == category["id"]


def test_buy_rejects_a_non_transfer_category(
    client: TestClient, registered_user: dict, investment_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    category = client.post(
        "/api/v1/categories", json={"name": "Spesa", "type": "expense"}, headers=headers
    ).json()

    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": investment_account["id"],
            "symbol": "AAPL",
            "asset_type": "stock",
            "type": "buy",
            "quantity": "10",
            "price": "140.00",
            "date": "2026-09-01",
            "category_id": category["id"],
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert client.get("/api/v1/portfolio/transactions", headers=headers).json() == []
