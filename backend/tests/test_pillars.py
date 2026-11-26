"""
The plan's four pillars and what they rest on: goals with a target date,
goals marked reached, and holdings as goal sources valued from the caches.

Dates are relative to today because the waterfall and the pillars read the
month in progress.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.services.periods import add_months, month_start

GOALS_URL = "/api/v1/planning/goals"
WATERFALL_URL = "/api/v1/planning/waterfall"
PILLARS_URL = "/api/v1/planning/pillars"

TODAY = date.today()


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    # A buy caches today's price through the (patched) provider; the reads
    # under test must then never call out, which `_no_network` enforces.
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_from_yahoo_finance", lambda symbol: Decimal("50.00")
    )
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_currency_from_yahoo_finance", lambda symbol: "EUR"
    )
    for target in ("app.routers.portfolio.get_rate", "app.services.net_worth.get_rate"):
        monkeypatch.setattr(target, lambda db, f, t, d: Decimal("1"))


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("a read path called out")

    for target in (
        "app.services.asset_prices._fetch_from_yahoo_finance",
        "app.services.exchange_rates._fetch_from_frankfurter",
    ):
        monkeypatch.setattr(target, fail)


def _account(client: TestClient, headers: dict, name: str, balance: str = "0", type_="checking"):
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": type_, "currency": "EUR", "starting_balance": balance},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _goal(client: TestClient, headers: dict, **kwargs) -> dict:
    response = client.post(GOALS_URL, json=kwargs, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _map(client: TestClient, headers: dict, goal_id: str, account_id: str, asset_id=None):
    payload = {"account_id": account_id}
    if asset_id is not None:
        payload["asset_id"] = asset_id
    return client.post(f"{GOALS_URL}/{goal_id}/sources", json=payload, headers=headers)


def _income(client: TestClient, headers: dict, account_id: str, amount: str) -> None:
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "amount": amount,
            "currency": "EUR",
            "date": TODAY.isoformat(),
            "type": "income",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _buy(client: TestClient, headers: dict, account_id: str, symbol: str, quantity: str) -> str:
    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": account_id,
            "symbol": symbol,
            "asset_type": "etf",
            "type": "buy",
            "quantity": quantity,
            "price": "40.00",
            "date": TODAY.isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["asset"]["id"]


def _step(body: dict, name: str) -> dict:
    return next(s for s in body["steps"] if s["name"] == name)


def _dated(name: str, amount: str, months_ahead: int) -> dict:
    return {
        "name": name,
        "kind": "medium_term",
        "target_mode": "fixed_amount",
        "target_amount": amount,
        "target_date": add_months(TODAY, months_ahead).isoformat(),
    }


# ---------------------------------------------------------------------------
# Target dates
# ---------------------------------------------------------------------------


def test_a_target_date_needs_a_medium_term_fixed_amount_goal(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    due = add_months(TODAY, 12).isoformat()

    emergency = client.post(
        GOALS_URL,
        json={
            "name": "Emergenza",
            "kind": "emergency_fund",
            "target_mode": "fixed_amount",
            "target_amount": "5000.00",
            "target_date": due,
        },
        headers=headers,
    )
    dynamic = client.post(
        GOALS_URL,
        json={
            "name": "Casa",
            "kind": "medium_term",
            "target_mode": "months_of_primary_expenses",
            "target_months": "6",
            "target_date": due,
        },
        headers=headers,
    )
    past = client.post(GOALS_URL, json=_dated("Auto", "10000.00", -1), headers=headers)

    assert emergency.status_code == 422
    assert dynamic.status_code == 422
    assert past.status_code == 422
    assert (
        client.post(GOALS_URL, json=_dated("Auto", "10000.00", 12), headers=headers).status_code
        == 201
    )


def test_a_new_goal_without_priority_is_placed_by_its_date(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    _goal(
        client,
        headers,
        name="Emergenza",
        kind="emergency_fund",
        priority=0,
        target_mode="fixed_amount",
        target_amount="5000.00",
    )
    _goal(client, headers, name="PAC", kind="long_term", priority=1, target_mode="open_ended")

    _goal(client, headers, **_dated("Mutuo", "50000.00", 60))
    _goal(client, headers, **_dated("Auto", "10000.00", 12))
    _goal(client, headers, **_dated("Viaggio", "3000.00", 24))

    body = client.get(GOALS_URL, headers=headers).json()

    # Nearest deadline first inside pillar 3. The numbers only order a
    # pillar's own goals, so they must rise there and nowhere else.
    assert [g["name"] for g in body] == ["Emergenza", "Auto", "Viaggio", "Mutuo", "PAC"]
    planned = [g["priority"] for g in body if g["kind"] == "medium_term"]
    assert planned == sorted(set(planned))


def test_a_dated_goal_reports_its_timetable(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    checking = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi", type_="savings")
    _income(client, headers, checking["id"], "2000.00")  # 10% quota = 200
    goal = _goal(client, headers, **_dated("Auto", "1200.00", 11))  # 12 contributions
    _map(client, headers, goal["id"], savings["id"])

    step = _step(client.get(WATERFALL_URL, headers=headers).json(), "Auto")

    assert step["months_left"] == 12
    assert Decimal(step["this_month_amount"]) == Decimal("200.00")
    # 1000 left after this month, over the 11 months after it.
    assert Decimal(step["required_monthly"]) == Decimal("90.91")
    assert Decimal(step["monthly_pace"]) == Decimal("200.00")
    assert step["on_track"] is True
    # 200 now, then 1000 at 200 a month: five more months.
    assert step["projected_date"] == add_months(month_start(TODAY), 5).isoformat()


def test_executing_the_month_does_not_lower_what_each_month_needs(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    checking = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi", type_="savings")
    _income(client, headers, checking["id"], "2000.00")
    client.patch(
        "/api/v1/planning/plan",
        json={"default_source_account_id": checking["id"]},
        headers=headers,
    )
    goal = _goal(client, headers, **_dated("Auto", "1200.00", 11))
    _map(client, headers, goal["id"], savings["id"])

    executed = client.post(
        f"{WATERFALL_URL}/execute",
        json={
            "items": [
                {"goal_id": goal["id"], "from_account_id": checking["id"], "amount": "200.00"}
            ]
        },
        headers=headers,
    )
    assert executed.status_code == 200, executed.text
    step = _step(client.get(WATERFALL_URL, headers=headers).json(), "Auto")

    assert Decimal(step["allocated_amount"]) == 0
    # Measured on the gap as it stood before this month's giroconto.
    assert Decimal(step["this_month_amount"]) == Decimal("200.00")
    # 1000 left after this month, over the 11 months after it.
    assert Decimal(step["required_monthly"]) == Decimal("90.91")
    assert Decimal(step["monthly_pace"]) == Decimal("200.00")
    assert step["on_track"] is True


def test_a_goal_the_quota_cannot_reach_is_behind(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    checking = _account(client, headers, "Conto")
    _income(client, headers, checking["id"], "1000.00")  # quota 100
    _goal(client, headers, **_dated("Auto", "6000.00", 5))  # 6 months: 1000 each

    step = _step(client.get(WATERFALL_URL, headers=headers).json(), "Auto")

    # 5900 left after this month's 100, over 5 months.
    assert Decimal(step["required_monthly"]) == Decimal("1180.00")
    assert step["on_track"] is False
    assert step["projected_date"] == add_months(month_start(TODAY), 59).isoformat()


# ---------------------------------------------------------------------------
# Completed goals
# ---------------------------------------------------------------------------


def test_a_reached_goal_leaves_the_cascade_and_frees_its_accounts(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    savings = _account(client, headers, "Risparmi", "1000.00", type_="savings")
    goal = _goal(client, headers, **_dated("Auto", "1000.00", 6))
    _map(client, headers, goal["id"], savings["id"])

    response = client.patch(
        f"{GOALS_URL}/{goal['id']}", json={"completed_at": TODAY.isoformat()}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == []

    steps = client.get(WATERFALL_URL, headers=headers).json()["steps"]
    assert [s["name"] for s in steps] == []
    # Still listed, so it can be reopened.
    assert [g["name"] for g in client.get(GOALS_URL, headers=headers).json()] == ["Auto"]

    other = _goal(client, headers, **_dated("Divano", "800.00", 6))
    assert _map(client, headers, other["id"], savings["id"]).status_code == 201


def test_only_a_fixed_amount_goal_can_be_reached(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    goal = _goal(
        client,
        headers,
        name="Emergenza",
        kind="emergency_fund",
        priority=0,
        target_mode="months_of_primary_expenses",
        target_months="6",
    )

    response = client.patch(
        f"{GOALS_URL}/{goal['id']}", json={"completed_at": TODAY.isoformat()}, headers=headers
    )

    # An emergency fund is drained and refilled, never "done".
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Holdings as sources
# ---------------------------------------------------------------------------


def test_a_holding_funds_a_goal_valued_from_the_cache(
    client: TestClient, registered_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = registered_user["auth_headers"]
    broker = _account(client, headers, "Broker", "1000.00", type_="investment")
    asset_id = _buy(client, headers, broker["id"], "XEON.DE", "10")  # cached at 50
    goal = _goal(client, headers, **_dated("Mutuo", "5000.00", 36))
    assert _map(client, headers, goal["id"], broker["id"], asset_id).status_code == 201

    _no_network(monkeypatch)
    step = _step(client.get(WATERFALL_URL, headers=headers).json(), "Mutuo")

    assert Decimal(step["current_amount"]) == Decimal("500.00")
    assert step["has_unpriced_sources"] is False


def test_a_holding_and_its_account_cash_are_separate_sources(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    broker = _account(client, headers, "Broker", "1000.00", type_="investment")
    asset_id = _buy(client, headers, broker["id"], "XEON.DE", "10")
    first = _goal(client, headers, **_dated("Mutuo", "5000.00", 36))
    second = _goal(client, headers, **_dated("Auto", "2000.00", 12))

    assert _map(client, headers, first["id"], broker["id"], asset_id).status_code == 201
    assert _map(client, headers, second["id"], broker["id"], asset_id).status_code == 409
    # The broker's uninvested cash is another thing and may fund another goal.
    assert _map(client, headers, second["id"], broker["id"]).status_code == 201


def test_a_holding_not_in_the_account_is_rejected(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    broker = _account(client, headers, "Broker", "1000.00", type_="investment")
    other = _account(client, headers, "Altro broker", "1000.00", type_="investment")
    asset_id = _buy(client, headers, broker["id"], "XEON.DE", "10")
    goal = _goal(client, headers, **_dated("Mutuo", "5000.00", 36))

    assert _map(client, headers, goal["id"], other["id"], asset_id).status_code == 422


def test_an_unpriced_holding_is_flagged_not_zeroed_silently(
    client: TestClient, registered_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = registered_user["auth_headers"]
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_currency_from_yahoo_finance", lambda symbol: "USD"
    )
    broker = _account(client, headers, "Broker", "1000.00", type_="investment")
    asset_id = _buy(client, headers, broker["id"], "VOO", "1")  # USD, no cached USD→EUR
    goal = _goal(client, headers, **_dated("Mutuo", "5000.00", 36))
    _map(client, headers, goal["id"], broker["id"], asset_id)

    _no_network(monkeypatch)
    step = _step(client.get(WATERFALL_URL, headers=headers).json(), "Mutuo")

    assert Decimal(step["current_amount"]) == 0
    assert step["has_unpriced_sources"] is True


# ---------------------------------------------------------------------------
# The pillars
# ---------------------------------------------------------------------------


def _pillar(body: dict, key: str) -> dict:
    return next(p for p in body["pillars"] if p["key"] == key)


def test_pillars_split_the_money_by_purpose(
    client: TestClient, registered_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = registered_user["auth_headers"]
    _account(client, headers, "Conto", "1500.00")
    deposit = _account(client, headers, "Deposito", "4000.00", type_="savings")
    broker = _account(client, headers, "Broker", "2000.00", type_="investment")
    parked = _buy(client, headers, broker["id"], "XEON.DE", "20")  # 1000, for the car
    _buy(client, headers, broker["id"], "VWCE.DE", "10")  # 500, free
    emergency = _goal(
        client,
        headers,
        name="Emergenza",
        kind="emergency_fund",
        priority=0,
        target_mode="fixed_amount",
        target_amount="6000.00",
    )
    _map(client, headers, emergency["id"], deposit["id"])
    car = _goal(client, headers, **_dated("Auto", "3000.00", 12))
    _map(client, headers, car["id"], broker["id"], parked)
    _goal(client, headers, name="PAC", kind="long_term", target_mode="open_ended")

    _no_network(monkeypatch)
    response = client.get(PILLARS_URL, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    operating = _pillar(body, "operating")
    assert Decimal(operating["current"]) == Decimal("1500.00")
    # No complete month of history: the target is unknown, not zero.
    assert operating["target"] is None

    emergency_pillar = _pillar(body, "emergency")
    assert Decimal(emergency_pillar["current"]) == Decimal("4000.00")
    assert Decimal(emergency_pillar["gap"]) == Decimal("2000.00")

    planned = _pillar(body, "planned")
    assert [s["name"] for s in planned["steps"]] == ["Auto"]
    assert Decimal(planned["current"]) == Decimal("1000.00")

    investing = _pillar(body, "investing")
    items = {i["kind"]: i for i in investing["items"]}
    # The parked XEON belongs to the car, not to the portfolio.
    assert Decimal(items["free_holdings"]["available"]) == Decimal("500.00")
    # The broker's cash after the two buys (2000 - 800 - 400).
    assert Decimal(items["uninvested_cash"]["available"]) == Decimal("800.00")
    assert investing["target"] is None


# ---------------------------------------------------------------------------
# The cascade moves the operating surplus, taxes first
# ---------------------------------------------------------------------------


def _spend_last_month(client: TestClient, headers: dict, account_id: str, amount: str) -> None:
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "amount": f"-{amount}",
            "currency": "EUR",
            "date": add_months(month_start(TODAY), -1).isoformat(),
            "type": "expense",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _set_source(client: TestClient, headers: dict, account_id: str) -> None:
    response = client.patch(
        "/api/v1/planning/plan", json={"default_source_account_id": account_id}, headers=headers
    )
    assert response.status_code == 200, response.text


def test_the_cascade_moves_what_the_operating_accounts_hold_beyond_their_target(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    checking = _account(client, headers, "Conto", "11000")
    _spend_last_month(client, headers, checking["id"], "1000")  # pillar 1 target: 1000
    _income(client, headers, checking["id"], "2000")  # quota 200; balance 12000
    _set_source(client, headers, checking["id"])
    deposit = _account(client, headers, "Deposito", type_="savings")
    emergency = _goal(
        client,
        headers,
        name="Emergenza",
        kind="emergency_fund",
        priority=0,
        target_mode="fixed_amount",
        target_amount="6000.00",
    )
    _map(client, headers, emergency["id"], deposit["id"])
    car_account = _account(client, headers, "Salvadanaio", type_="savings")
    car = _goal(client, headers, **_dated("Auto", "8000.00", 12))
    _map(client, headers, car["id"], car_account["id"])

    body = client.get(WATERFALL_URL, headers=headers).json()

    # 12000 - 1000 needed for the month = 11000, not just the 200 of quota.
    assert Decimal(body["operating_surplus"]) == Decimal("11000.00")
    assert Decimal(body["budget"]) == Decimal("11000.00")
    assert Decimal(_step(body, "Emergenza")["allocated_amount"]) == Decimal("6000.00")
    assert Decimal(_step(body, "Auto")["allocated_amount"]) == Decimal("5000.00")
    assert all(a["kind"] == "transfer" for a in body["actions"])


def test_without_history_only_the_quota_is_moved(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    checking = _account(client, headers, "Conto", "11000")
    _income(client, headers, checking["id"], "2000")
    emergency = _goal(
        client,
        headers,
        name="Emergenza",
        kind="emergency_fund",
        priority=0,
        target_mode="fixed_amount",
        target_amount="6000.00",
    )

    body = client.get(WATERFALL_URL, headers=headers).json()

    # Pillar 1's target is unknown: sweeping "everything above zero" would
    # move the rent too.
    assert body["operating_surplus"] is None
    assert Decimal(_step(body, emergency["name"])["allocated_amount"]) == Decimal("200.00")


def test_the_surplus_is_capped_at_what_the_source_account_holds(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    small = _account(client, headers, "Conto stipendio", "1500")
    _account(client, headers, "Conto grande", "10000")
    _spend_last_month(client, headers, small["id"], "1000")  # balance 500, target 1000
    _set_source(client, headers, small["id"])
    _goal(
        client,
        headers,
        name="Emergenza",
        kind="emergency_fund",
        priority=0,
        target_mode="fixed_amount",
        target_amount="6000.00",
    )

    body = client.get(WATERFALL_URL, headers=headers).json()

    # 9500 of surplus overall, but every giroconto would leave the 500 account.
    assert Decimal(body["operating_surplus"]) == Decimal("9500.00")
    assert Decimal(body["budget"]) == Decimal("500.00")


def test_the_tax_provision_comes_before_the_emergency_fund(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    checking = _account(client, headers, "Conto", "1000")
    _spend_last_month(client, headers, checking["id"], "1000")  # target 1000, balance 0
    taxes = _account(client, headers, "Conto Tasse", type_="savings")
    assert (
        client.post(
            "/api/v1/flat-rate/sources", json={"account_id": taxes["id"]}, headers=headers
        ).status_code
        == 201
    )
    invoice = client.post(
        "/api/v1/flat-rate/invoices",
        json={"client": "Acme", "issue_date": TODAY.isoformat(), "amount": "10000.00"},
        headers=headers,
    ).json()
    collected = client.post(
        f"/api/v1/flat-rate/invoices/{invoice['id']}/collect",
        json={"collected_on": TODAY.isoformat(), "account_id": checking["id"]},
        headers=headers,
    )
    assert collected.status_code == 200, collected.text
    _set_source(client, headers, checking["id"])
    deposit = _account(client, headers, "Deposito", type_="savings")
    emergency = _goal(
        client,
        headers,
        name="Emergenza",
        kind="emergency_fund",
        priority=0,
        target_mode="fixed_amount",
        target_amount="3000.00",
    )
    _map(client, headers, emergency["id"], deposit["id"])

    body = client.get(WATERFALL_URL, headers=headers).json()
    rung = body["tax_provision"]
    gap = Decimal(rung["gap"])

    assert gap > 0
    # Asked for the 1st of the month, the requirement is still today's: the
    # balances include today's collection, so its taxes must be in too.
    first_of_month = client.get(
        f"{WATERFALL_URL}?date={month_start(TODAY).isoformat()}", headers=headers
    ).json()
    assert Decimal(first_of_month["tax_provision"]["gap"]) == gap
    assert Decimal(rung["allocated_amount"]) == gap
    first = body["actions"][0]
    assert first["purpose"] == "tax_provision"
    assert first["to_account_id"] == taxes["id"]
    # The emergency fund gets what's left after the State's share.
    assert Decimal(_step(body, "Emergenza")["allocated_amount"]) == min(
        Decimal("3000.00"), Decimal(body["budget"]) - gap
    )

    executed = client.post(
        f"{WATERFALL_URL}/execute",
        json={
            "items": [
                {
                    "to_account_id": taxes["id"],
                    "from_account_id": checking["id"],
                    "amount": first["amount"],
                }
            ]
        },
        headers=headers,
    )
    assert executed.status_code == 200, executed.text
    after = client.get(WATERFALL_URL, headers=headers).json()
    assert Decimal(after["tax_provision"]["gap"]) == 0


def test_a_goal_accounts_excess_is_shown_in_pillar_1(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    deposit = _account(client, headers, "Deposito", "9000", type_="savings")
    for name, kind, amount in (
        ("Emergenza", "emergency_fund", "6000"),
        ("Vacanze", "medium_term", "2000"),
    ):
        goal = _goal(
            client, headers, name=name, kind=kind, target_mode="fixed_amount", target_amount=amount
        )
        _map(client, headers, goal["id"], deposit["id"])

    body = client.get(PILLARS_URL, headers=headers).json()

    operating = _pillar(body, "operating")
    [item] = operating["items"]
    assert item["kind"] == "goal_account_excess"
    assert Decimal(item["available"]) == Decimal("1000.00")
    assert Decimal(_pillar(body, "emergency")["current"]) == Decimal("6000.00")
    assert Decimal(_pillar(body, "planned")["current"]) == Decimal("2000.00")


def test_a_one_off_from_the_surplus_is_not_projected_as_a_monthly_pace(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    checking = _account(client, headers, "Conto", "5000")
    _spend_last_month(client, headers, checking["id"], "1000")  # target 1000, balance 4000
    _income(client, headers, checking["id"], "1000")  # quota 100; surplus 4000
    _set_source(client, headers, checking["id"])
    piggy = _account(client, headers, "Salvadanaio", type_="savings")
    car = _goal(client, headers, **_dated("Auto", "10000.00", 9))  # 10 contributions
    _map(client, headers, car["id"], piggy["id"])

    step = _step(client.get(WATERFALL_URL, headers=headers).json(), "Auto")

    # This month moves the 4000 of surplus…
    assert Decimal(step["this_month_amount"]) == Decimal("4000.00")
    # …but from next month only the 100 of quota comes in, against the
    # 6000 / 9 = 666.67 still needed.
    assert Decimal(step["monthly_pace"]) == Decimal("100.00")
    assert Decimal(step["required_monthly"]) == Decimal("666.67")
    assert step["on_track"] is False
    assert step["projected_date"] == add_months(month_start(TODAY), 60).isoformat()
