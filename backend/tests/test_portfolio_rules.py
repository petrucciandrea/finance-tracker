"""
Pillar-4 guardrails (targets, caps, idle cash, minimum invested share),
the presets that fill the targets in, and the plan's alerts.

Every product is priced at 50 EUR by the patched provider.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.services.periods import add_months

RULES_URL = "/api/v1/planning/portfolio-rules"
TODAY = date.today()


@pytest.fixture(autouse=True)
def _prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_from_yahoo_finance", lambda symbol: Decimal("50.00")
    )
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_currency_from_yahoo_finance", lambda symbol: "EUR"
    )
    for target in (
        "app.routers.portfolio.get_rate",
        "app.services.net_worth.get_rate",
        "app.services.portfolio_allocation.get_rate",
    ):
        monkeypatch.setattr(target, lambda db, f, t, d: Decimal("1"))


def _account(client: TestClient, headers: dict, name: str, balance: str, type_: str) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": type_, "currency": "EUR", "starting_balance": balance},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _buy(client: TestClient, headers: dict, account_id: str, symbol: str, quantity: str) -> str:
    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": account_id,
            "symbol": symbol,
            "asset_type": "etf",
            "type": "buy",
            "quantity": quantity,
            "price": "50.00",
            "date": TODAY.isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["asset"]["id"]


def _rule(client: TestClient, headers: dict, **payload):
    return client.post(RULES_URL, json=payload, headers=headers)


def _status(client: TestClient, headers: dict) -> dict:
    response = client.get(RULES_URL, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _alerts(client: TestClient, headers: dict) -> list[dict]:
    response = client.get("/api/v1/alerts", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["alerts"]


@pytest.fixture
def broker(client: TestClient, registered_user: dict) -> dict:
    return _account(client, registered_user["auth_headers"], "Broker", "1000", "investment")


# ---------------------------------------------------------------------------
# Rules and their state
# ---------------------------------------------------------------------------


def test_a_target_band_reads_over_under_or_ok(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "VWCE.DE", "14")  # 700 equity
    _buy(client, headers, broker["id"], "XEON.DE", "6")  # 300 money market
    assert (
        _rule(
            client,
            headers,
            kind="target",
            dimension="asset_class",
            bucket="equity",
            target_pct="60",
            tolerance_pct="5",
        ).status_code
        == 201
    )
    assert (
        _rule(
            client,
            headers,
            kind="target",
            dimension="asset_class",
            bucket="money_market",
            target_pct="35",
        ).status_code
        == 201
    )  # tolerance defaults to 5

    rules = {r["rule"]["bucket"]: r for r in _status(client, headers)["rules"]}

    assert rules["equity"]["state"] == "over"  # 70 > 60 + 5
    assert rules["equity"]["actual_pct"] == 70.0
    assert rules["money_market"]["state"] == "ok"  # 30 within 35 ± 5


def test_targets_of_a_dimension_cannot_exceed_100(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    _rule(client, headers, kind="target", dimension="asset_class", bucket="equity", target_pct="80")

    response = _rule(
        client, headers, kind="target", dimension="asset_class", bucket="bond", target_pct="30"
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "target", "dimension": "sector", "bucket": "energy", "target_pct": "10"},
        {"kind": "target", "dimension": "region", "bucket": "atlantis", "target_pct": "10"},
        {"kind": "max_share", "dimension": "region", "bucket": "italy", "min_pct": "10"},
        {"kind": "excess_cash", "threshold_amount": "1000", "threshold_months": "3"},
        {"kind": "excess_cash"},
        {"kind": "max_share", "dimension": "position", "bucket": "not-an-asset", "max_pct": "10"},
    ],
)
def test_malformed_rules_are_refused(
    client: TestClient, registered_user: dict, payload: dict
) -> None:
    assert _rule(client, registered_user["auth_headers"], **payload).status_code == 422


def test_a_rule_on_a_poorly_classified_dimension_is_not_judged(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "ZZZZ.DE", "10")  # unknown to the reference file
    _rule(
        client, headers, kind="max_share", dimension="region", bucket="north_america", max_pct="50"
    )

    [rule] = _status(client, headers)["rules"]

    assert rule["state"] == "unknown"
    assert rule["reason"] == "coverage"


def test_a_position_cap(client: TestClient, registered_user: dict, broker: dict) -> None:
    headers = registered_user["auth_headers"]
    qdve = _buy(client, headers, broker["id"], "QDVE.DE", "6")  # 300
    _buy(client, headers, broker["id"], "VWCE.DE", "14")  # 700
    assert (
        _rule(
            client, headers, kind="max_share", dimension="position", bucket=qdve, max_pct="20"
        ).status_code
        == 201
    )

    [rule] = _status(client, headers)["rules"]

    assert rule["state"] == "over"
    assert rule["actual_pct"] == 30.0
    assert rule["label"] == "QDVE.DE"


def test_a_preset_replaces_the_targets_only(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    _rule(client, headers, kind="target", dimension="asset_class", bucket="equity", target_pct="90")
    _rule(client, headers, kind="min_invested", min_pct="50")

    response = client.post(f"{RULES_URL}/preset", json={"preset": "60_40"}, headers=headers)

    assert response.status_code == 200, response.text
    kinds = sorted((r["rule"]["kind"], r["rule"]["bucket"]) for r in response.json()["rules"])
    assert kinds == [("min_invested", None), ("target", "bond"), ("target", "equity")]
    presets = client.get("/api/v1/planning/portfolio-presets", headers=headers).json()
    # Generic mixes as weights: no preset names a product.
    assert all(t["dimension"] in ("asset_class", "region") for p in presets for t in p["targets"])


def test_new_money_goes_to_the_buckets_below_target() -> None:
    from app.schemas import AllocationBucketValue, ExposureDimension, PortfolioAllocation
    from app.services.portfolio_rules import split_contribution

    alloc = PortfolioAllocation(
        dimension=ExposureDimension.asset_class,
        base_currency="EUR",
        total=Decimal("1000"),
        classified_value=Decimal("1000"),
        coverage=100.0,
        buckets=[
            AllocationBucketValue(bucket="equity", value=Decimal("800"), percentage=80.0),
            AllocationBucketValue(bucket="bond", value=Decimal("200"), percentage=20.0),
        ],
        unclassified_value=Decimal("0"),
        excluded_value=Decimal("0"),
        has_unpriced=False,
        stale_count=0,
        positions=[],
    )

    split = split_contribution(
        alloc, {"equity": Decimal("60"), "bond": Decimal("40")}, Decimal("200")
    )

    # On 1200, bonds should be 480: they get all 200 and equities nothing —
    # nothing is sold to rebalance.
    assert [(s.bucket, s.amount) for s in split] == [("bond", Decimal("200.00"))]


# ---------------------------------------------------------------------------
# Idle cash and invested share
# ---------------------------------------------------------------------------


def _month_of_spending(client: TestClient, headers: dict, account_id: str, amount: str) -> None:
    previous = add_months(TODAY.replace(day=1), -1).isoformat()
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "amount": f"-{amount}",
            "currency": "EUR",
            "date": previous,
            "type": "expense",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def test_idle_cash_leaves_out_what_the_emergency_fund_still_needs(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    checking = _account(client, headers, "Conto", "12000", "checking")
    _month_of_spending(client, headers, checking["id"], "1000")  # 1 month of spend = 1000
    deposit = _account(client, headers, "Deposito", "2000", "savings")
    emergency = client.post(
        "/api/v1/planning/goals",
        json={
            "name": "Emergenza",
            "kind": "emergency_fund",
            "priority": 0,
            "target_mode": "fixed_amount",
            "target_amount": "6000",
        },
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/planning/goals/{emergency['id']}/sources",
        json={"account_id": deposit["id"]},
        headers=headers,
    )
    _buy(client, headers, broker["id"], "VWCE.DE", "20")  # 1000 invested, broker cash 0
    _rule(client, headers, kind="excess_cash", threshold_months="3")
    _rule(client, headers, kind="min_invested", min_pct="40")

    body = _status(client, headers)

    # Operating 11000 - 1 month (1000) - emergency gap (4000) = 6000 idle.
    assert Decimal(body["idle_cash"]) == Decimal("6000.00")
    assert body["invested_share"] == round(1000 / 7000 * 100, 1)
    states = {r["rule"]["kind"]: r for r in body["rules"]}
    assert states["excess_cash"]["state"] == "over"
    assert Decimal(states["excess_cash"]["limit_amount"]) == Decimal("3000.00")
    assert states["min_invested"]["state"] == "under"


def test_without_history_idle_cash_is_unknown(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    _account(client, headers, "Conto", "12000", "checking")
    _rule(client, headers, kind="excess_cash", threshold_amount="1000")

    body = _status(client, headers)

    assert body["idle_cash"] is None
    assert body["rules"][0]["state"] == "unknown"


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def test_a_broken_rule_raises_a_once_a_month_alert(
    client: TestClient, registered_user: dict, broker: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "QDVE.DE", "10")
    _rule(
        client,
        headers,
        kind="max_share",
        dimension="sector",
        bucket="information_technology",
        max_pct="40",
    )

    def fail(*args, **kwargs):
        raise AssertionError("the banner called out")

    monkeypatch.setattr("app.services.asset_prices._fetch_from_yahoo_finance", fail)
    alerts = [a for a in _alerts(client, headers) if a["kind"] == "allocation_over_cap"]

    assert len(alerts) == 1
    assert alerts[0]["repeat"] == "once"
    assert alerts[0]["percentage"] == 100.0
    assert alerts[0]["limit_percentage"] == 40.0
    assert alerts[0]["id"].endswith(TODAY.strftime("%Y-%m"))


def test_a_short_dated_goal_in_equities_is_flagged(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    vwce = _buy(client, headers, broker["id"], "VWCE.DE", "20")
    goal = client.post(
        "/api/v1/planning/goals",
        json={
            "name": "Anticipo casa",
            "kind": "medium_term",
            "target_mode": "fixed_amount",
            "target_amount": "20000",
            "target_date": add_months(TODAY, 24).isoformat(),
        },
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/planning/goals/{goal['id']}/sources",
        json={"account_id": broker["id"], "asset_id": vwce},
        headers=headers,
    )

    kinds = {a["kind"]: a for a in _alerts(client, headers)}

    assert kinds["goal_horizon_mismatch"]["label"] == "Anticipo casa"
    assert kinds["goal_horizon_mismatch"]["percentage"] == 100.0


def test_buying_with_the_emergency_fund_short_is_flagged(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    client.post(
        "/api/v1/planning/goals",
        json={
            "name": "Emergenza",
            "kind": "emergency_fund",
            "priority": 0,
            "target_mode": "fixed_amount",
            "target_amount": "6000",
        },
        headers=headers,
    )
    _buy(client, headers, broker["id"], "VWCE.DE", "2")

    kinds = {a["kind"] for a in _alerts(client, headers)}

    assert "investing_without_emergency_fund" in kinds


def test_a_goal_due_within_two_weeks_is_flagged(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    due = TODAY.replace(day=28) if TODAY.day < 20 else add_months(TODAY.replace(day=5), 1)
    # Only meaningful when that date is within the window from today.
    response = client.post(
        "/api/v1/planning/goals",
        json={
            "name": "Auto",
            "kind": "medium_term",
            "target_mode": "fixed_amount",
            "target_amount": "5000",
            "target_date": due.isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text

    kinds = {a["kind"] for a in _alerts(client, headers)}

    assert ("goal_due_soon" in kinds) == ((due - TODAY).days <= 14)


def test_targets_are_replaced_per_dimension_in_one_go(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    client.post(f"{RULES_URL}/preset", json={"preset": "all_world"}, headers=headers)
    _rule(
        client,
        headers,
        kind="max_share",
        dimension="sector",
        bucket="information_technology",
        max_pct="30",
    )

    # From 100% equity to 70/30: one at a time the sum would pass 100.
    response = client.put(
        f"{RULES_URL}/targets",
        json={
            "dimension": "asset_class",
            "tolerance_pct": "3",
            "targets": [
                {"bucket": "equity", "target_pct": "70"},
                {"bucket": "bond", "target_pct": "30"},
                {"bucket": "crypto", "target_pct": "0"},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    rules = [r["rule"] for r in response.json()["rules"]]
    asset_class = {r["bucket"]: r for r in rules if r["dimension"] == "asset_class"}
    assert set(asset_class) == {"equity", "bond"}  # the 0 isn't stored
    assert Decimal(asset_class["bond"]["tolerance_pct"]) == Decimal("3")
    # The preset's regions and the sector cap are untouched.
    assert sum(1 for r in rules if r["dimension"] == "region") == 7
    assert any(r["kind"] == "max_share" for r in rules)


def test_replaced_targets_cannot_exceed_100(client: TestClient, registered_user: dict) -> None:
    response = client.put(
        f"{RULES_URL}/targets",
        json={
            "dimension": "region",
            "targets": [
                {"bucket": "north_america", "target_pct": "70"},
                {"bucket": "emerging", "target_pct": "40"},
            ],
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422
