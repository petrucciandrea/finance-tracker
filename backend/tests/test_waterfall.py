"""
Tests for the waterfall savings engine (phase C): goal CRUD, funding
source mapping, and the cascade itself.

The cascade's interesting behaviour is all about what happens at the
edges — an unknown target, an overfunded rung, an open-ended rung — so
most of these set up a specific shape and assert one number.
"""

from decimal import Decimal

from fastapi.testclient import TestClient

GOALS_URL = "/api/v1/planning/goals"
WATERFALL_URL = "/api/v1/planning/waterfall"


def _account(client: TestClient, headers: dict, name: str, balance: str | None = None) -> dict:
    payload: dict = {"name": name, "type": "checking", "currency": "EUR"}
    if balance is not None:
        payload["starting_balance"] = balance
    response = client.post("/api/v1/accounts", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _category(client: TestClient, headers: dict, name: str, ctype: str, level=None) -> dict:
    payload: dict = {"name": name, "type": ctype}
    if level is not None:
        payload["necessity_level"] = level
    response = client.post("/api/v1/categories", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _transaction(
    client: TestClient, headers: dict, account_id: str, amount: str, txn_date: str, category_id=None
) -> None:
    payload: dict = {
        "account_id": account_id,
        "amount": amount,
        "currency": "EUR",
        "date": txn_date,
        "type": "expense" if Decimal(amount) < 0 else "income",
    }
    if category_id is not None:
        payload["category_id"] = category_id
    response = client.post("/api/v1/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text


def _goal(client: TestClient, headers: dict, **kwargs) -> dict:
    response = client.post(GOALS_URL, json=kwargs, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _map_source(client: TestClient, headers: dict, goal_id: str, account_id: str):
    return client.post(
        f"{GOALS_URL}/{goal_id}/sources", json={"account_id": account_id}, headers=headers
    )


def _income_of(client: TestClient, headers: dict, account_id: str, amount: str) -> None:
    salary = _category(client, headers, "Stipendio", "income")
    _transaction(client, headers, account_id, amount, "2026-09-01", salary["id"])


def _step(body: dict, name: str) -> dict:
    return next(s for s in body["steps"] if s["name"] == name)


# ---------------------------------------------------------------------------
# Goal CRUD and validation
# ---------------------------------------------------------------------------

def test_dynamic_goal_requires_target_months(client: TestClient, registered_user: dict) -> None:
    response = client.post(
        GOALS_URL,
        json={
            "name": "Emergenza",
            "kind": "emergency_fund",
            "priority": 0,
            "target_mode": "months_of_primary_expenses",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422


def test_fixed_goal_rejects_target_months(client: TestClient, registered_user: dict) -> None:
    response = client.post(
        GOALS_URL,
        json={
            "name": "Auto",
            "kind": "medium_term",
            "priority": 1,
            "target_mode": "fixed_amount",
            "target_amount": "8000.00",
            "target_months": "6",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422


def test_open_ended_goal_takes_no_target(client: TestClient, registered_user: dict) -> None:
    response = client.post(
        GOALS_URL,
        json={
            "name": "PAC",
            "kind": "long_term",
            "priority": 2,
            "target_mode": "open_ended",
            "target_amount": "1000.00",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422


def test_a_second_open_ended_goal_is_rejected(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    _goal(client, headers, name="PAC", kind="long_term", priority=2, target_mode="open_ended")

    response = client.post(
        GOALS_URL,
        json={"name": "Pensione", "kind": "long_term", "priority": 3, "target_mode": "open_ended"},
        headers=headers,
    )

    # It would absorb the remainder and close the cascade, so a second one
    # could never receive anything whatever the priorities.
    assert response.status_code == 409


def test_goals_are_listed_in_cascade_order(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    _goal(client, headers, name="Terzo", kind="long_term", priority=5, target_mode="open_ended")
    _goal(
        client, headers, name="Primo", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="1000.00",
    )
    _goal(
        client, headers, name="Secondo", kind="medium_term", priority=2,
        target_mode="fixed_amount", target_amount="2000.00",
    )

    body = client.get(GOALS_URL, headers=headers).json()

    assert [g["name"] for g in body] == ["Primo", "Secondo", "Terzo"]


# ---------------------------------------------------------------------------
# Funding sources
# ---------------------------------------------------------------------------

def test_an_account_can_fund_only_one_goal(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers, "Risparmi")
    first = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="5000.00",
    )
    second = _goal(
        client, headers, name="Auto", kind="medium_term", priority=1,
        target_mode="fixed_amount", target_amount="8000.00",
    )

    assert _map_source(client, headers, first["id"], account["id"]).status_code == 201
    # Counting one balance toward two goals would make the cascade believe
    # there is twice the money.
    assert _map_source(client, headers, second["id"], account["id"]).status_code == 409


def test_deleting_an_account_that_funds_a_goal_is_rejected(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers, "Risparmi")
    goal = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="5000.00",
    )
    _map_source(client, headers, goal["id"], account["id"])

    response = client.delete(f"/api/v1/accounts/{account['id']}", headers=headers)

    assert response.status_code == 409


def test_detaching_a_source_frees_the_account(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _account(client, headers, "Risparmi")
    goal = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="5000.00",
    )
    source = _map_source(client, headers, goal["id"], account["id"]).json()

    detached = client.delete(
        f"{GOALS_URL}/{goal['id']}/sources/{source['id']}", headers=headers
    )
    assert detached.status_code == 204

    other = _goal(
        client, headers, name="Auto", kind="medium_term", priority=1,
        target_mode="fixed_amount", target_amount="8000.00",
    )
    assert _map_source(client, headers, other["id"], account["id"]).status_code == 201


# ---------------------------------------------------------------------------
# The cascade
# ---------------------------------------------------------------------------

def test_quota_fills_the_first_rung_before_the_second(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income_of(client, headers, main["id"], "2000.00")  # 10% savings -> 200

    first = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="5000.00",
    )
    second = _goal(
        client, headers, name="Auto", kind="medium_term", priority=1,
        target_mode="fixed_amount", target_amount="8000.00",
    )
    _map_source(client, headers, first["id"], _account(client, headers, "Emergenza")["id"])
    _map_source(client, headers, second["id"], _account(client, headers, "Auto")["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    assert Decimal(body["savings_quota"]) == Decimal("200.00")
    assert Decimal(_step(body, "Emergenza")["allocated_amount"]) == Decimal("200.00")
    assert Decimal(_step(body, "Auto")["allocated_amount"]) == Decimal("0.00")


def test_a_funded_rung_lets_the_next_one_through(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income_of(client, headers, main["id"], "2000.00")

    # Already above its 1000 target.
    emergency_account = _account(client, headers, "Emergenza", balance="1200.00")
    car_account = _account(client, headers, "Auto")
    first = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="1000.00",
    )
    second = _goal(
        client, headers, name="Auto", kind="medium_term", priority=1,
        target_mode="fixed_amount", target_amount="8000.00",
    )
    _map_source(client, headers, first["id"], emergency_account["id"])
    _map_source(client, headers, second["id"], car_account["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    emergency = _step(body, "Emergenza")
    assert emergency["is_funded"] is True
    # Overfunded must never "give money back".
    assert Decimal(emergency["allocated_amount"]) == Decimal("0.00")
    assert Decimal(_step(body, "Auto")["allocated_amount"]) == Decimal("200.00")


def test_an_open_ended_rung_absorbs_the_remainder(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income_of(client, headers, main["id"], "2000.00")

    emergency_account = _account(client, headers, "Emergenza", balance="900.00")
    pac_account = _account(client, headers, "PAC")
    first = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="1000.00",
    )
    pac = _goal(client, headers, name="PAC", kind="long_term", priority=1,
                target_mode="open_ended")
    _map_source(client, headers, first["id"], emergency_account["id"])
    _map_source(client, headers, pac["id"], pac_account["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    # 900 of 1000 is 90%, below the 95% band, so the gap of 100 is filled
    # first and the PAC takes what's left.
    assert Decimal(_step(body, "Emergenza")["allocated_amount"]) == Decimal("100.00")
    assert Decimal(_step(body, "PAC")["allocated_amount"]) == Decimal("100.00")
    assert Decimal(body["unallocated_amount"]) == Decimal("0.00")


def test_a_nearly_full_rung_does_not_starve_the_next(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income_of(client, headers, main["id"], "2000.00")

    # 970 of 1000 is 97%: within the band, so no micro top-up.
    emergency_account = _account(client, headers, "Emergenza", balance="970.00")
    car_account = _account(client, headers, "Auto")
    first = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="1000.00",
    )
    second = _goal(
        client, headers, name="Auto", kind="medium_term", priority=1,
        target_mode="fixed_amount", target_amount="8000.00",
    )
    _map_source(client, headers, first["id"], emergency_account["id"])
    _map_source(client, headers, second["id"], car_account["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    assert Decimal(_step(body, "Emergenza")["allocated_amount"]) == Decimal("0.00")
    assert Decimal(_step(body, "Auto")["allocated_amount"]) == Decimal("200.00")


def test_a_drained_fund_returns_to_the_top(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income_of(client, headers, main["id"], "2000.00")

    emergency_account = _account(client, headers, "Emergenza", balance="1000.00")
    car_account = _account(client, headers, "Auto", balance="8000.00")
    first = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="1000.00",
    )
    second = _goal(
        client, headers, name="Auto", kind="medium_term", priority=1,
        target_mode="fixed_amount", target_amount="8000.00",
    )
    _map_source(client, headers, first["id"], emergency_account["id"])
    _map_source(client, headers, second["id"], car_account["id"])

    # Both full: nothing to do.
    full = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()
    assert Decimal(full["unallocated_amount"]) == Decimal("200.00")

    # Drain the emergency fund. Its gap reopens and, having the lowest
    # priority number, it is back at the top with no special-casing.
    _transaction(client, headers, emergency_account["id"], "-600.00", "2026-09-15")

    after = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()
    assert Decimal(_step(after, "Emergenza")["allocated_amount"]) == Decimal("200.00")
    assert Decimal(_step(after, "Auto")["allocated_amount"]) == Decimal("0.00")


def test_a_dynamic_target_follows_primary_expenses(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    casa = _category(client, headers, "Casa", "expense", level="primary")
    for month in ("06", "07", "08"):
        _transaction(client, headers, main["id"], "-800.00", f"2026-{month}-10", casa["id"])

    goal = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="months_of_primary_expenses", target_months="6",
    )
    _map_source(client, headers, goal["id"], _account(client, headers, "Emergenza")["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    # 800/month average x 6 months.
    assert Decimal(_step(body, "Emergenza")["target_amount"]) == Decimal("4800.00")


def test_an_unknown_dynamic_target_is_skipped_not_treated_as_funded(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income_of(client, headers, main["id"], "2000.00")
    # No complete month of history, so the primary average is unknown.

    emergency = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="months_of_primary_expenses", target_months="6",
    )
    car = _goal(
        client, headers, name="Auto", kind="medium_term", priority=1,
        target_mode="fixed_amount", target_amount="8000.00",
    )
    _map_source(client, headers, emergency["id"], _account(client, headers, "Emergenza")["id"])
    _map_source(client, headers, car["id"], _account(client, headers, "Auto")["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    step = _step(body, "Emergenza")
    assert step["target_unavailable"] is True
    assert step["target_amount"] is None
    # The crucial part: not funded, so the UI says "need more history"
    # rather than "done" — but its quota isn't consumed either.
    assert step["is_funded"] is False
    assert Decimal(step["allocated_amount"]) == Decimal("0.00")
    assert Decimal(_step(body, "Auto")["allocated_amount"]) == Decimal("200.00")


def test_zero_income_produces_no_actions(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    goal = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="5000.00",
    )
    _map_source(client, headers, goal["id"], _account(client, headers, "Emergenza")["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    assert Decimal(body["savings_quota"]) == Decimal("0.00")
    assert body["actions"] == []


# ---------------------------------------------------------------------------
# Suggested actions
# ---------------------------------------------------------------------------

def test_an_executable_transfer_is_suggested(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    emergency_account = _account(client, headers, "Emergenza")
    _income_of(client, headers, main["id"], "2000.00")
    client.patch(
        "/api/v1/planning/plan",
        json={"default_source_account_id": main["id"]},
        headers=headers,
    )

    goal = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="5000.00",
    )
    _map_source(client, headers, goal["id"], emergency_account["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    assert len(body["actions"]) == 1
    action = body["actions"][0]
    assert action["kind"] == "transfer"
    assert action["from_account_id"] == main["id"]
    assert action["to_account_id"] == emergency_account["id"]
    assert Decimal(action["amount"]) == Decimal("200.00")


def test_without_a_source_account_the_action_is_advice(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income_of(client, headers, main["id"], "2000.00")
    goal = _goal(
        client, headers, name="Emergenza", kind="emergency_fund", priority=0,
        target_mode="fixed_amount", target_amount="5000.00",
    )
    _map_source(client, headers, goal["id"], _account(client, headers, "Emergenza")["id"])

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    # Never silently dropped — the user is told what is missing.
    assert body["actions"][0]["kind"] == "advice"
    assert "conto di accredito" in body["actions"][0]["reason"]


def test_a_goal_with_no_account_yields_advice(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income_of(client, headers, main["id"], "2000.00")
    client.patch(
        "/api/v1/planning/plan",
        json={"default_source_account_id": main["id"]},
        headers=headers,
    )
    _goal(
        client, headers, name="PAC azionario", kind="long_term", priority=0,
        target_mode="open_ended",
    )

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    assert body["actions"][0]["kind"] == "advice"
    assert "Nessun conto collegato" in body["actions"][0]["reason"]
