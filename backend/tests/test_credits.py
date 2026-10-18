"""
Tests for credits: spend fronted for other people (`lent_amount`) and the
income that pays it back (`repays_transaction_id`).

The story every test tells: a 100 EUR dinner on the card, 75 EUR of it for
friends. The spend is 25 from the day it is booked; the other 75 is a credit
in net worth until the friends hand it back in cash.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.services.necessity import UNCLASSIFIED, income_total, spend_by_necessity

TRANSACTIONS = "/api/v1/transactions"
NET_WORTH = "/api/v1/portfolio/net-worth"


@pytest.fixture
def headers(registered_user: dict) -> dict:
    return registered_user["auth_headers"]


@pytest.fixture
def card(client: TestClient, headers: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Carta", "type": "checking", "currency": "EUR", "starting_balance": "1000"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def cash(client: TestClient, headers: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Contanti", "type": "cash", "currency": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def restaurants(client: TestClient, headers: dict) -> dict:
    response = client.post(
        "/api/v1/categories",
        json={"name": "Ristoranti", "type": "expense", "necessity_level": "discretionary"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post(client: TestClient, headers: dict, **fields) -> TestClient:
    response = client.post(TRANSACTIONS, json=fields, headers=headers)
    return response


def _dinner(
    client: TestClient,
    headers: dict,
    account: dict,
    category: dict,
    *,
    lent: str | None = "75.00",
    amount: str = "-100.00",
    on: str = "2026-10-10",
) -> dict:
    fields: dict = {
        "account_id": account["id"],
        "category_id": category["id"],
        "amount": amount,
        "currency": "EUR",
        "date": on,
        "type": "expense",
        "description": "Cena",
    }
    if lent is not None:
        fields["lent_amount"] = lent
    response = _post(client, headers, **fields)
    assert response.status_code == 201, response.text
    return response.json()


def _repay(
    client: TestClient,
    headers: dict,
    account: dict,
    expense: dict,
    *,
    amount: str = "75.00",
    on: str = "2026-11-02",
    currency: str = "EUR",
):
    return _post(
        client,
        headers,
        account_id=account["id"],
        amount=amount,
        currency=currency,
        date=on,
        type="income",
        repays_transaction_id=expense["id"],
        description="Rimborso cena",
    )


def _category_name(client: TestClient, headers: dict, category_id: str | None) -> str | None:
    if category_id is None:
        return None
    categories = client.get("/api/v1/categories", headers=headers).json()
    return next(c["name"] for c in categories if c["id"] == category_id)


def _summary(client: TestClient, headers: dict, **params) -> list[dict]:
    response = client.get(f"{TRANSACTIONS}/summary", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ---------------------------------------------------------------------------
# Spend is netted immediately
# ---------------------------------------------------------------------------

def test_summary_counts_only_the_own_share_of_an_expense(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    _dinner(client, headers, card, restaurants)

    items = _summary(client, headers, group_by=["category"], date_from="2026-10-01")

    assert len(items) == 1
    assert Decimal(items[0]["total_amount_base_currency"]) == Decimal("-25.00")


def test_budget_and_necessity_spend_use_the_own_share(
    client: TestClient,
    headers: dict,
    registered_user: dict,
    db_session: Session,
    card: dict,
    restaurants: dict,
) -> None:
    _dinner(client, headers, card, restaurants)
    client.post(
        "/api/v1/budgets",
        json={
            "category_id": restaurants["id"],
            "period": "monthly",
            "amount_limit": "50.00",
            "start_date": "2026-10-01",
        },
        headers=headers,
    )

    status = client.get("/api/v1/budgets/status?date=2026-10-20", headers=headers).json()
    assert Decimal(status[0]["amount_spent"]) == Decimal("25.00")
    assert status[0]["is_over_budget"] is False

    user = db_session.query(User).filter_by(email=registered_user["email"]).one()
    buckets = spend_by_necessity(
        db_session, user, date_from=date(2026, 10, 1), date_to=date(2026, 10, 31)
    )
    assert buckets == {"discretionary": Decimal("25.00")}
    assert UNCLASSIFIED not in buckets


def test_an_expense_without_lent_amount_is_unchanged(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    _dinner(client, headers, card, restaurants, lent=None)

    items = _summary(client, headers, date_from="2026-10-01")

    assert Decimal(items[0]["total_amount_base_currency"]) == Decimal("-100.00")


# ---------------------------------------------------------------------------
# A repayment is cash, not income, and does not change the spend
# ---------------------------------------------------------------------------

def test_repayment_moves_cash_but_is_not_income_and_not_spend(
    client: TestClient,
    headers: dict,
    registered_user: dict,
    db_session: Session,
    card: dict,
    cash: dict,
    restaurants: dict,
) -> None:
    expense = _dinner(client, headers, card, restaurants)

    response = _repay(client, headers, cash, expense)

    assert response.status_code == 201, response.text
    repayment = response.json()
    assert repayment["repays_transaction_id"] == expense["id"]
    # Nobody categorizes the friends paying back: it files itself under "Rimborsi".
    assert _category_name(client, headers, repayment["category_id"]) == "Rimborsi"

    # The summary shows the 25 of spend and no income at all.
    items = _summary(client, headers, date_from="2026-10-01")
    assert len(items) == 1
    assert Decimal(items[0]["total_amount_base_currency"]) == Decimal("-25.00")

    user = db_session.query(User).filter_by(email=registered_user["email"]).one()
    assert income_total(
        db_session, user, date_from=date(2026, 11, 1), date_to=date(2026, 11, 30)
    ) == Decimal("0")

    # But the cash really arrived.
    balances = {
        a["account_name"]: Decimal(a["balance"])
        for a in client.get(NET_WORTH, headers=headers).json()["accounts"]
    }
    assert balances["Contanti"] == Decimal("75.00")


def test_expense_reports_how_much_was_repaid(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)
    assert Decimal(expense["lent_amount"]) == Decimal("75")
    assert Decimal(expense["repaid_amount"]) == Decimal("0")

    _repay(client, headers, cash, expense, amount="30.00")

    fetched = client.get(f"{TRANSACTIONS}/{expense['id']}", headers=headers).json()
    assert Decimal(fetched["repaid_amount"]) == Decimal("30")
    listed = client.get(TRANSACTIONS, params={"type": "expense"}, headers=headers).json()
    assert Decimal(listed["data"][0]["repaid_amount"]) == Decimal("30")

    # An expense with nothing fronted has no repaid amount at all.
    plain = _dinner(client, headers, card, restaurants, lent=None)
    assert plain["repaid_amount"] is None


def test_open_credits_lists_only_expenses_with_something_left(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    open_one = _dinner(client, headers, card, restaurants, on="2026-10-01")
    settled = _dinner(client, headers, card, restaurants, on="2026-10-02")
    _dinner(client, headers, card, restaurants, lent=None, on="2026-10-03")
    assert _repay(client, headers, cash, settled, on="2026-10-05").status_code == 201

    response = client.get(f"{TRANSACTIONS}/open-credits", headers=headers)

    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [open_one["id"]]


# ---------------------------------------------------------------------------
# Net worth: the credit is an asset, never cash
# ---------------------------------------------------------------------------

def test_credit_is_in_net_worth_but_not_in_cash_and_closes_on_repayment(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    before = client.get(NET_WORTH, headers=headers).json()
    expense = _dinner(client, headers, card, restaurants, on=date.today().isoformat())

    after = client.get(NET_WORTH, headers=headers).json()
    # Cash dropped by the whole 100, but net worth only by the 25 that was spent.
    assert Decimal(after["total_cash_balance"]) == Decimal(before["total_cash_balance"]) - 100
    assert Decimal(after["total_credits_value"]) == Decimal("75")
    assert Decimal(after["total_net_worth"]) == Decimal(before["total_net_worth"]) - 25

    _repay(client, headers, cash, expense, on=date.today().isoformat())

    settled = client.get(NET_WORTH, headers=headers).json()
    assert Decimal(settled["total_credits_value"]) == Decimal("0")
    assert Decimal(settled["total_cash_balance"]) == Decimal(before["total_cash_balance"]) - 25
    # Money changed form, wealth did not.
    assert Decimal(settled["total_net_worth"]) == Decimal(after["total_net_worth"])


def test_history_carries_the_credit_per_date(
    client: TestClient,
    headers: dict,
    card: dict,
    cash: dict,
    restaurants: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.routers.portfolio.get_rate_history",
        lambda db, from_currency, to_currency, start_date, end_date: {},
    )
    expense = _dinner(client, headers, card, restaurants, on=date.today().isoformat())

    points = client.get("/api/v1/portfolio/history?period=1m", headers=headers).json()["points"]
    assert Decimal(points[-1]["total_credits_base_currency"]) == Decimal("75")

    _repay(client, headers, cash, expense, amount="75.00", on=date.today().isoformat())
    points = client.get("/api/v1/portfolio/history?period=1m", headers=headers).json()["points"]
    assert Decimal(points[-1]["total_credits_base_currency"]) == Decimal("0")


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def test_lent_amount_only_on_expenses_and_within_the_amount(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    too_much = _post(
        client,
        headers,
        account_id=card["id"],
        category_id=restaurants["id"],
        amount="-100.00",
        currency="EUR",
        date="2026-10-10",
        type="expense",
        lent_amount="100.01",
    )
    assert too_much.status_code == 422

    on_income = _post(
        client,
        headers,
        account_id=card["id"],
        amount="100.00",
        currency="EUR",
        date="2026-10-10",
        type="income",
        lent_amount="10.00",
    )
    assert on_income.status_code == 422


def test_repayment_must_target_an_expense_with_a_credit(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    plain = _dinner(client, headers, card, restaurants, lent=None)

    response = _repay(client, headers, cash, plain)

    assert response.status_code == 422


def test_repayments_cannot_exceed_the_amount_fronted(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)
    assert _repay(client, headers, cash, expense, amount="50.00").status_code == 201

    over = _repay(client, headers, cash, expense, amount="25.01")
    assert over.status_code == 422

    assert _repay(client, headers, cash, expense, amount="25.00").status_code == 201


def test_repayment_must_share_the_currency_and_not_precede_the_expense(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)

    assert _repay(client, headers, cash, expense, currency="USD").status_code == 422
    assert _repay(client, headers, cash, expense, on="2026-10-09").status_code == 422


def test_repayment_reuses_an_existing_rimborsi_category_and_keeps_a_chosen_one(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    own = client.post(
        "/api/v1/categories",
        json={"name": "Rimborsi", "type": "income", "excluded_from_income_base": True},
        headers=headers,
    ).json()
    other = client.post(
        "/api/v1/categories", json={"name": "Altro", "type": "income"}, headers=headers
    ).json()
    expense = _dinner(client, headers, card, restaurants)

    automatic = _repay(client, headers, cash, expense, amount="10.00").json()
    chosen = _post(
        client,
        headers,
        account_id=cash["id"],
        category_id=other["id"],
        amount="10.00",
        currency="EUR",
        date="2026-11-02",
        type="income",
        repays_transaction_id=expense["id"],
    ).json()

    # The user's own "Rimborsi" is reused, not duplicated.
    assert automatic["category_id"] == own["id"]
    assert chosen["category_id"] == other["id"]
    names = [c["name"] for c in client.get("/api/v1/categories", headers=headers).json()]
    assert names.count("Rimborsi") == 1


def test_expense_with_repayments_cannot_be_deleted_or_shrunk(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)
    repayment = _repay(client, headers, cash, expense, amount="50.00").json()

    assert client.delete(f"{TRANSACTIONS}/{expense['id']}", headers=headers).status_code == 409
    below = client.patch(
        f"{TRANSACTIONS}/{expense['id']}", json={"lent_amount": "49.99"}, headers=headers
    )
    assert below.status_code == 409
    cleared = client.patch(
        f"{TRANSACTIONS}/{expense['id']}", json={"lent_amount": None}, headers=headers
    )
    assert cleared.status_code == 409
    later = client.patch(
        f"{TRANSACTIONS}/{expense['id']}", json={"date": "2026-11-03"}, headers=headers
    )
    assert later.status_code == 409

    # Deleting the repayment frees the expense and reopens the whole credit.
    assert client.delete(f"{TRANSACTIONS}/{repayment['id']}", headers=headers).status_code == 204
    assert client.delete(f"{TRANSACTIONS}/{expense['id']}", headers=headers).status_code == 204


def test_expense_lent_amount_can_be_edited_within_bounds(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)

    response = client.patch(
        f"{TRANSACTIONS}/{expense['id']}", json={"lent_amount": "40.00"}, headers=headers
    )
    assert response.status_code == 200
    assert Decimal(response.json()["lent_amount"]) == Decimal("40")

    items = _summary(client, headers, date_from="2026-10-01")
    assert Decimal(items[0]["total_amount_base_currency"]) == Decimal("-60.00")

    assert client.patch(
        f"{TRANSACTIONS}/{expense['id']}", json={"lent_amount": "100.01"}, headers=headers
    ).status_code == 422
    assert client.patch(
        f"{TRANSACTIONS}/{expense['id']}", json={"lent_amount": None}, headers=headers
    ).status_code == 200


def test_existing_income_can_become_a_repayment_and_back(
    client: TestClient,
    headers: dict,
    registered_user: dict,
    db_session: Session,
    card: dict,
    restaurants: dict,
) -> None:
    expense = _dinner(client, headers, card, restaurants)
    income_category = client.post(
        "/api/v1/categories", json={"name": "Altro", "type": "income"}, headers=headers
    ).json()
    # E.g. a row that arrived through the CSV import as plain income.
    imported = _post(
        client,
        headers,
        account_id=card["id"],
        category_id=income_category["id"],
        amount="75.00",
        currency="EUR",
        date="2026-10-12",
        type="income",
    ).json()
    user = db_session.query(User).filter_by(email=registered_user["email"]).one()
    window = {"date_from": date(2026, 10, 1), "date_to": date(2026, 10, 31)}
    assert income_total(db_session, user, **window) == Decimal("75")

    linked = client.patch(
        f"{TRANSACTIONS}/{imported['id']}",
        json={"repays_transaction_id": expense["id"]},
        headers=headers,
    )
    assert linked.status_code == 200, linked.text
    # Filed under "Rimborsi" now, whatever it was before.
    assert _category_name(client, headers, linked.json()["category_id"]) == "Rimborsi"
    assert income_total(db_session, user, **window) == Decimal("0")

    unlinked = client.patch(
        f"{TRANSACTIONS}/{imported['id']}",
        json={"repays_transaction_id": None},
        headers=headers,
    )
    assert unlinked.status_code == 200, unlinked.text
    # A plain income again: it leaves "Rimborsi" (kept out of the income base) for "Varie".
    assert _category_name(client, headers, unlinked.json()["category_id"]) == "Varie"
    assert income_total(db_session, user, **window) == Decimal("75")


def test_repayment_edit_rechecks_the_cap(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)
    first = _repay(client, headers, cash, expense, amount="50.00").json()
    _repay(client, headers, cash, expense, amount="20.00")

    over = client.patch(f"{TRANSACTIONS}/{first['id']}", json={"amount": "55.01"}, headers=headers)
    assert over.status_code == 422
    fine = client.patch(f"{TRANSACTIONS}/{first['id']}", json={"amount": "55.00"}, headers=headers)
    assert fine.status_code == 200, fine.text


def test_repayment_and_invoice_collection_exclude_each_other(
    client: TestClient, headers: dict, card: dict, cash: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)
    repayment = _repay(client, headers, cash, expense).json()
    invoices = "/api/v1/flat-rate/invoices"
    first = client.post(
        invoices,
        json={"client": "Acme", "issue_date": "2026-10-01", "amount": "75.00"},
        headers=headers,
    ).json()

    # A repayment is not a client's payment...
    collect = client.post(
        f"{invoices}/{first['id']}/collect",
        json={"collected_on": "2026-11-02", "transaction_id": repayment["id"]},
        headers=headers,
    )
    assert collect.status_code == 409

    # ...and an income that collects an invoice cannot be turned into one.
    second = client.post(
        invoices,
        json={"client": "Beta", "issue_date": "2026-10-01", "amount": "40.00"},
        headers=headers,
    ).json()
    collected = client.post(
        f"{invoices}/{second['id']}/collect",
        json={"collected_on": "2026-11-03", "account_id": cash["id"]},
        headers=headers,
    ).json()
    link = client.patch(
        f"{TRANSACTIONS}/{collected['transaction_id']}",
        json={"repays_transaction_id": expense["id"]},
        headers=headers,
    )
    assert link.status_code == 409


# ---------------------------------------------------------------------------
# Settled in kind: the friend pays the next time, no cash changes hands
# ---------------------------------------------------------------------------

def _offset(
    client: TestClient,
    headers: dict,
    account: dict,
    expense: dict,
    *,
    amount: str = "75.00",
    on: str = "2026-10-24",
    **extra,
):
    return client.post(
        f"{TRANSACTIONS}/credit-offsets",
        json={
            "credit_transaction_id": expense["id"],
            "account_id": account["id"],
            "amount": amount,
            "date": on,
            **extra,
        },
        headers=headers,
    )


def test_offset_closes_the_credit_without_cash_or_income(
    client: TestClient,
    headers: dict,
    registered_user: dict,
    db_session: Session,
    card: dict,
    restaurants: dict,
) -> None:
    expense = _dinner(client, headers, card, restaurants, on=date.today().isoformat())
    before = client.get(NET_WORTH, headers=headers).json()

    response = _offset(
        client, headers, card, expense, on=date.today().isoformat(),
        category_id=restaurants["id"], necessity_level_override="useful",
    )

    assert response.status_code == 201, response.text
    spend, repayment = response.json()
    assert (spend["type"], Decimal(spend["amount"])) == ("expense", Decimal("-75"))
    assert spend["lent_amount"] is None
    assert spend["category_id"] == restaurants["id"]
    assert spend["necessity_level_override"] == "useful"
    assert (repayment["type"], Decimal(repayment["amount"])) == ("income", Decimal("75"))
    assert repayment["repays_transaction_id"] == expense["id"]
    assert _category_name(client, headers, repayment["category_id"]) == "Rimborsi"
    assert spend["offset_transaction_id"] == repayment["id"]
    assert repayment["offset_transaction_id"] == spend["id"]

    after = client.get(NET_WORTH, headers=headers).json()
    # The two legs cancel: no cash moved, the credit is gone, and the spend is
    # real consumption, so net worth fell by exactly that.
    assert after["total_cash_balance"] == before["total_cash_balance"]
    assert Decimal(after["total_credits_value"]) == Decimal("0")
    assert Decimal(after["total_net_worth"]) == Decimal(before["total_net_worth"]) - 75

    user = db_session.query(User).filter_by(email=registered_user["email"]).one()
    assert income_total(
        db_session, user, date_from=date.today().replace(day=1), date_to=date.today()
    ) == Decimal("0")
    fetched = client.get(f"{TRANSACTIONS}/{expense['id']}", headers=headers).json()
    assert Decimal(fetched["repaid_amount"]) == Decimal("75")
    assert client.get(f"{TRANSACTIONS}/open-credits", headers=headers).json() == []


def test_offset_spend_lands_in_the_month_of_the_offset(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants, on="2026-09-10")
    offset = _offset(client, headers, card, expense, amount="40.00", on="2026-10-24")
    assert offset.status_code == 201, offset.text

    september = _summary(client, headers, date_from="2026-09-01", date_to="2026-09-30")
    october = _summary(client, headers, date_from="2026-10-01", date_to="2026-10-31")

    assert Decimal(september[0]["total_amount_base_currency"]) == Decimal("-25.00")
    assert Decimal(october[0]["total_amount_base_currency"]) == Decimal("-40.00")


def test_offset_without_a_category_falls_back_to_varie_and_can_be_partial(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)

    first = _offset(client, headers, card, expense, amount="30.00")
    second = _offset(client, headers, card, expense, amount="45.00")

    assert first.status_code == 201 and second.status_code == 201
    assert _category_name(client, headers, first.json()[0]["category_id"]) == "Varie"
    assert client.get(f"{TRANSACTIONS}/open-credits", headers=headers).json() == []


def test_offset_cannot_exceed_the_open_credit_or_change_currency(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)

    assert _offset(client, headers, card, expense, amount="75.01").status_code == 422
    assert _offset(client, headers, card, expense, on="2026-10-09").status_code == 422
    usd = client.post(
        "/api/v1/accounts",
        json={"name": "Dollari", "type": "checking", "currency": "USD"},
        headers=headers,
    ).json()
    assert _offset(client, headers, usd, expense).status_code == 422
    plain = _dinner(client, headers, card, restaurants, lent=None)
    assert _offset(client, headers, card, plain).status_code == 422
    # Nothing was written by the refusals.
    still_open = client.get(f"{TRANSACTIONS}/open-credits", headers=headers).json()
    assert Decimal(still_open[0]["repaid_amount"]) == 0


def test_offset_respects_a_closed_account(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)
    # The opening balance is dated today, so that is the earliest possible close.
    closed = client.patch(
        f"/api/v1/accounts/{card['id']}",
        json={"closed_at": date.today().isoformat()},
        headers=headers,
    )
    assert closed.status_code == 200, closed.text

    after_close = (date.today() + timedelta(days=1)).isoformat()
    assert _offset(client, headers, card, expense, on=after_close).status_code == 409


def test_offset_legs_are_deleted_together_and_keep_amount_and_date(
    client: TestClient, headers: dict, card: dict, restaurants: dict
) -> None:
    expense = _dinner(client, headers, card, restaurants)
    spend, repayment = _offset(client, headers, card, expense).json()

    assert client.patch(
        f"{TRANSACTIONS}/{spend['id']}", json={"amount": "-50.00"}, headers=headers
    ).status_code == 409
    assert client.patch(
        f"{TRANSACTIONS}/{repayment['id']}", json={"date": "2026-10-25"}, headers=headers
    ).status_code == 409
    assert client.patch(
        f"{TRANSACTIONS}/{repayment['id']}",
        json={"repays_transaction_id": None},
        headers=headers,
    ).status_code == 409
    # Description and category stay free, and are not mirrored onto the other leg.
    renamed = client.patch(
        f"{TRANSACTIONS}/{spend['id']}",
        json={"description": "Pizza", "category_id": restaurants["id"]},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    other = client.get(f"{TRANSACTIONS}/{repayment['id']}", headers=headers).json()
    assert other["description"] != "Pizza"
    assert _category_name(client, headers, other["category_id"]) == "Rimborsi"

    # The credit cannot be deleted while the offset stands, and deleting one
    # leg retires both and reopens the credit.
    assert client.delete(f"{TRANSACTIONS}/{expense['id']}", headers=headers).status_code == 409
    assert client.delete(f"{TRANSACTIONS}/{repayment['id']}", headers=headers).status_code == 204
    assert client.get(f"{TRANSACTIONS}/{spend['id']}", headers=headers).status_code == 404
    reopened = client.get(f"{TRANSACTIONS}/open-credits", headers=headers).json()
    assert [t["id"] for t in reopened] == [expense["id"]]
    assert Decimal(reopened[0]["repaid_amount"]) == 0
