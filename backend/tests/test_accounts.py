"""
Tests for the accounts router, focused on the `starting_balance` option on
creation: it should produce an opening-balance transaction (type=transfer,
so it never counts toward a budget or forces a "Varie" category) rather
than a separate stored balance field.
"""

from decimal import Decimal

import httpx
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


# ---------------------------------------------------------------------------
# Closing
# ---------------------------------------------------------------------------

def _account(client: TestClient, headers: dict, name: str = "Old bank") -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": "checking", "currency": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _transaction(client: TestClient, headers: dict, account_id: str, on: str) -> httpx.Response:
    return client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "amount": "-10.00",
            "currency": "EUR",
            "date": on,
            "type": "expense",
        },
        headers=headers,
    )


def _close(client: TestClient, headers: dict, account_id: str, on: str | None) -> httpx.Response:
    return client.patch(
        f"/api/v1/accounts/{account_id}", json={"closed_at": on}, headers=headers
    )


def test_close_and_reopen_account(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)

    response = _close(client, headers, account["id"], "2026-03-31")
    assert response.status_code == 200, response.text
    assert response.json()["closed_at"] == "2026-03-31"

    # Closed is not deleted: it stays listed, with its date.
    listed = client.get("/api/v1/accounts", headers=headers).json()
    assert [a["closed_at"] for a in listed] == ["2026-03-31"]

    response = _close(client, headers, account["id"], None)
    assert response.status_code == 200, response.text
    assert response.json()["closed_at"] is None


def test_editing_the_name_leaves_closed_at_alone(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    _close(client, headers, account["id"], "2026-03-31")

    response = client.patch(
        f"/api/v1/accounts/{account['id']}", json={"name": "Renamed"}, headers=headers
    )
    assert response.json()["closed_at"] == "2026-03-31"


def test_cannot_close_in_the_future(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    response = _close(client, headers, account["id"], "2999-01-01")
    assert response.status_code == 422, response.text


def test_cannot_close_before_the_last_movement(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    _transaction(client, headers, account["id"], "2026-04-15")

    assert _close(client, headers, account["id"], "2026-04-14").status_code == 409
    # On the day of the last movement is fine.
    assert _close(client, headers, account["id"], "2026-04-15").status_code == 200


def test_closed_account_refuses_movements_after_the_close(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    _close(client, headers, account["id"], "2026-03-31")

    assert _transaction(client, headers, account["id"], "2026-04-01").status_code == 409
    # Back-dated corrections still go through.
    assert _transaction(client, headers, account["id"], "2026-03-31").status_code == 201


def test_closed_account_refuses_redating_a_movement_past_the_close(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    transaction = _transaction(client, headers, account["id"], "2026-03-01").json()
    _close(client, headers, account["id"], "2026-03-31")

    response = client.patch(
        f"/api/v1/transactions/{transaction['id']}", json={"date": "2026-04-02"}, headers=headers
    )
    assert response.status_code == 409, response.text

    response = client.patch(
        f"/api/v1/transactions/{transaction['id']}",
        json={"description": "still editable"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_giroconto_into_a_closed_account_is_refused(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    closed = _account(client, headers, "Old bank")
    other = _account(client, headers, "New bank")
    _close(client, headers, closed["id"], "2026-03-31")

    response = client.post(
        "/api/v1/transactions/transfers",
        json={
            "from_account_id": other["id"],
            "to_account_id": closed["id"],
            "amount": "50.00",
            "date": "2026-04-10",
        },
        headers=headers,
    )
    assert response.status_code == 409, response.text


def test_account_funding_a_goal_cannot_be_closed(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    goal = client.post(
        "/api/v1/planning/goals",
        json={
            "name": "Fondo emergenza",
            "kind": "emergency_fund",
            "priority": 0,
            "target_mode": "fixed_amount",
            "target_amount": "5000.00",
        },
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/planning/goals/{goal['id']}/sources",
        json={"account_id": account["id"]},
        headers=headers,
    )

    assert _close(client, headers, account["id"], "2026-03-31").status_code == 409


def test_closed_account_cannot_fund_a_goal(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    _close(client, headers, account["id"], "2026-03-31")
    goal = client.post(
        "/api/v1/planning/goals",
        json={
            "name": "Vacanze",
            "kind": "medium_term",
            "priority": 1,
            "target_mode": "fixed_amount",
            "target_amount": "1000.00",
        },
        headers=headers,
    ).json()

    response = client.post(
        f"/api/v1/planning/goals/{goal['id']}/sources",
        json={"account_id": account["id"]},
        headers=headers,
    )
    assert response.status_code == 409, response.text


def test_csv_preview_flags_rows_after_the_close(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    _close(client, headers, account["id"], "2026-03-31")

    csv_text = (
        "date,amount,currency,description\n"
        "2026-03-30,-5.00,EUR,before\n"
        "2026-04-02,-7.00,EUR,after\n"
    )
    response = client.post(
        "/api/v1/transactions/import",
        params={"account_id": account["id"]},
        files={"file": ("bank.csv", csv_text.encode("utf-8"), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    rows = {r["description"]: r for r in response.json()["rows"]}
    assert rows["before"]["is_parsable"] is True
    assert rows["after"]["is_parsable"] is False


def test_closed_account_keeps_its_balance_in_net_worth(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers)
    _transaction(client, headers, account["id"], "2026-03-01")
    _close(client, headers, account["id"], "2026-03-31")

    body = client.get("/api/v1/portfolio/net-worth", headers=headers).json()
    assert Decimal(body["total_cash_balance"]) == Decimal("-10.00")
