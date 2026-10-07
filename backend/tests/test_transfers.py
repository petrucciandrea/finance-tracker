"""
Tests for phase D: executing the waterfall's suggestions as two-sided
giroconti, and the rules that keep the two legs consistent afterwards.
"""

from decimal import Decimal

from fastapi.testclient import TestClient

GOALS_URL = "/api/v1/planning/goals"
WATERFALL_URL = "/api/v1/planning/waterfall"
EXECUTE_URL = "/api/v1/planning/waterfall/execute"
ALLOCATIONS_URL = "/api/v1/planning/waterfall/allocations"


def _account(
    client: TestClient, headers: dict, name: str, balance: str | None = None, currency: str = "EUR"
) -> dict:
    payload: dict = {"name": name, "type": "checking", "currency": currency}
    if balance is not None:
        payload["starting_balance"] = balance
    response = client.post("/api/v1/accounts", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _income(client: TestClient, headers: dict, account_id: str, amount: str) -> None:
    category = client.post(
        "/api/v1/categories", json={"name": "Stipendio", "type": "income"}, headers=headers
    ).json()
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category["id"],
            "amount": amount,
            "currency": "EUR",
            "date": "2026-09-01",
            "type": "income",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _goal_with_account(
    client: TestClient, headers: dict, name: str, account_id: str, target: str = "5000.00"
) -> dict:
    goal = client.post(
        GOALS_URL,
        json={
            "name": name,
            "kind": "emergency_fund",
            "priority": 0,
            "target_mode": "fixed_amount",
            "target_amount": target,
        },
        headers=headers,
    ).json()
    response = client.post(
        f"{GOALS_URL}/{goal['id']}/sources", json={"account_id": account_id}, headers=headers
    )
    assert response.status_code == 201, response.text
    return goal


def _balances(client: TestClient, headers: dict) -> dict:
    body = client.get("/api/v1/portfolio/net-worth", headers=headers).json()
    return {a["account_name"]: Decimal(a["balance"]) for a in body["accounts"]}


def _setup(client: TestClient, headers: dict, income: str = "2000.00") -> tuple[dict, dict, dict]:
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Emergenza")
    _income(client, headers, main["id"], income)
    client.patch(
        "/api/v1/planning/plan",
        json={"default_source_account_id": main["id"]},
        headers=headers,
    )
    goal = _goal_with_account(client, headers, "Emergenza", savings["id"])
    return main, savings, goal


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def test_execute_creates_two_mirrored_linked_legs(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main, savings, goal = _setup(client, headers)

    response = client.post(
        EXECUTE_URL,
        json={
            "date": "2026-09-20",
            "items": [
                {"goal_id": goal["id"], "from_account_id": main["id"], "amount": "200.00"}
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["transactions"]) == 2

    outgoing = next(t for t in body["transactions"] if Decimal(t["amount"]) < 0)
    incoming = next(t for t in body["transactions"] if Decimal(t["amount"]) > 0)
    assert Decimal(outgoing["amount"]) == Decimal("-200.00")
    assert Decimal(incoming["amount"]) == Decimal("200.00")
    assert outgoing["counterpart_transaction_id"] == incoming["id"]
    assert incoming["counterpart_transaction_id"] == outgoing["id"]
    # A giroconto is not a spend, so neither leg is categorised.
    assert outgoing["type"] == "transfer"
    assert outgoing["category_id"] is None


def test_execute_moves_the_balances_and_leaves_net_worth_alone(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main, savings, goal = _setup(client, headers)
    before = client.get("/api/v1/portfolio/net-worth", headers=headers).json()

    client.post(
        EXECUTE_URL,
        json={
            "date": "2026-09-20",
            "items": [
                {"goal_id": goal["id"], "from_account_id": main["id"], "amount": "200.00"}
            ],
        },
        headers=headers,
    )

    balances = _balances(client, headers)
    assert balances["Conto"] == Decimal("1800.00")
    assert balances["Emergenza"] == Decimal("200.00")

    after = client.get("/api/v1/portfolio/net-worth", headers=headers).json()
    # Money moved between the user's own buckets — net worth must not budge.
    assert Decimal(after["total_net_worth"]) == Decimal(before["total_net_worth"])


def test_executing_twice_does_not_offer_the_same_quota_again(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main, savings, goal = _setup(client, headers)

    first = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()
    assert Decimal(first["savings_quota"]) == Decimal("200.00")
    assert Decimal(first["steps"][0]["allocated_amount"]) == Decimal("200.00")

    client.post(
        EXECUTE_URL,
        json={
            "date": "2026-09-20",
            "items": [
                {"goal_id": goal["id"], "from_account_id": main["id"], "amount": "200.00"}
            ],
        },
        headers=headers,
    )

    second = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()
    assert Decimal(second["already_allocated"]) == Decimal("200.00")
    # Nothing left to suggest — otherwise following the page twice would
    # transfer the same money twice.
    assert Decimal(second["steps"][0]["allocated_amount"]) == Decimal("0.00")
    assert second["actions"] == []


def test_allocations_are_listed_for_the_period(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main, savings, goal = _setup(client, headers)
    client.post(
        EXECUTE_URL,
        json={
            "date": "2026-09-20",
            "items": [
                {"goal_id": goal["id"], "from_account_id": main["id"], "amount": "150.00"}
            ],
        },
        headers=headers,
    )

    body = client.get(f"{ALLOCATIONS_URL}?date=2026-09-25", headers=headers).json()

    assert len(body) == 1
    assert body[0]["goal_id"] == goal["id"]
    assert Decimal(body[0]["amount_base_currency"]) == Decimal("150.00")
    assert body[0]["period_start"] == "2026-09-01"


def test_allocations_of_another_period_are_not_counted(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main, savings, goal = _setup(client, headers)
    client.post(
        EXECUTE_URL,
        json={
            "date": "2026-08-20",
            "items": [
                {"goal_id": goal["id"], "from_account_id": main["id"], "amount": "200.00"}
            ],
        },
        headers=headers,
    )

    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()

    # August's transfer must not consume September's quota.
    assert Decimal(body["already_allocated"]) == Decimal("0.00")


def test_execute_rejects_a_goal_with_no_account(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income(client, headers, main["id"], "2000.00")
    goal = client.post(
        GOALS_URL,
        json={
            "name": "PAC",
            "kind": "long_term",
            "priority": 0,
            "target_mode": "open_ended",
        },
        headers=headers,
    ).json()

    response = client.post(
        EXECUTE_URL,
        json={"items": [{"goal_id": goal["id"], "from_account_id": main["id"],
                         "amount": "100.00"}]},
        headers=headers,
    )

    assert response.status_code == 422


def test_execute_rejects_a_transfer_to_the_same_account(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    _income(client, headers, main["id"], "2000.00")
    goal = _goal_with_account(client, headers, "Emergenza", main["id"])

    response = client.post(
        EXECUTE_URL,
        json={"items": [{"goal_id": goal["id"], "from_account_id": main["id"],
                         "amount": "100.00"}]},
        headers=headers,
    )

    # The legs would cancel out while the ledger still consumed the quota.
    assert response.status_code == 422


def test_execute_rejects_cross_currency(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    usd_savings = _account(client, headers, "Emergenza USD", currency="USD")
    _income(client, headers, main["id"], "2000.00")
    goal = _goal_with_account(client, headers, "Emergenza", usd_savings["id"])

    response = client.post(
        EXECUTE_URL,
        json={"items": [{"goal_id": goal["id"], "from_account_id": main["id"],
                         "amount": "100.00"}]},
        headers=headers,
    )

    assert response.status_code == 422


def test_a_rejected_item_leaves_no_half_executed_batch(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main, savings, good_goal = _setup(client, headers)
    # Second goal funded by the source account itself, so its item fails.
    bad_goal = client.post(
        GOALS_URL,
        json={
            "name": "Auto",
            "kind": "medium_term",
            "priority": 1,
            "target_mode": "fixed_amount",
            "target_amount": "8000.00",
        },
        headers=headers,
    ).json()
    client.post(
        f"{GOALS_URL}/{bad_goal['id']}/sources", json={"account_id": main["id"]}, headers=headers
    )

    response = client.post(
        EXECUTE_URL,
        json={
            "date": "2026-09-20",
            "items": [
                {"goal_id": good_goal["id"], "from_account_id": main["id"], "amount": "100.00"},
                {"goal_id": bad_goal["id"], "from_account_id": main["id"], "amount": "100.00"},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 422
    # Everything commits once at the end, so the first item didn't land.
    assert _balances(client, headers)["Emergenza"] == Decimal("0")
    assert client.get(f"{ALLOCATIONS_URL}?date=2026-09-20", headers=headers).json() == []


# ---------------------------------------------------------------------------
# Keeping the two legs consistent afterwards
# ---------------------------------------------------------------------------

def test_deleting_one_leg_deletes_both_and_frees_the_quota(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main, savings, goal = _setup(client, headers)
    executed = client.post(
        EXECUTE_URL,
        json={
            "date": "2026-09-20",
            "items": [
                {"goal_id": goal["id"], "from_account_id": main["id"], "amount": "200.00"}
            ],
        },
        headers=headers,
    ).json()
    outgoing = next(t for t in executed["transactions"] if Decimal(t["amount"]) < 0)

    deleted = client.delete(f"/api/v1/transactions/{outgoing['id']}", headers=headers)
    assert deleted.status_code == 204

    # Both legs gone, balances back where they started.
    balances = _balances(client, headers)
    assert balances["Conto"] == Decimal("2000.00")
    assert balances["Emergenza"] == Decimal("0")

    # And the quota is available again — a cancelled giroconto must not
    # keep consuming it for money that never moved.
    body = client.get(f"{WATERFALL_URL}?date=2026-09-20", headers=headers).json()
    assert Decimal(body["already_allocated"]) == Decimal("0.00")
    assert Decimal(body["steps"][0]["allocated_amount"]) == Decimal("200.00")


def test_editing_a_linked_legs_amount_is_rejected(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main, savings, goal = _setup(client, headers)
    executed = client.post(
        EXECUTE_URL,
        json={
            "date": "2026-09-20",
            "items": [
                {"goal_id": goal["id"], "from_account_id": main["id"], "amount": "200.00"}
            ],
        },
        headers=headers,
    ).json()
    leg_id = executed["transactions"][0]["id"]

    response = client.patch(
        f"/api/v1/transactions/{leg_id}", json={"amount": "-50.00"}, headers=headers
    )

    # Editing one side would silently desynchronise the pair.
    assert response.status_code == 409


def test_a_linked_legs_description_is_still_editable(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main, savings, goal = _setup(client, headers)
    executed = client.post(
        EXECUTE_URL,
        json={
            "date": "2026-09-20",
            "items": [
                {"goal_id": goal["id"], "from_account_id": main["id"], "amount": "200.00"}
            ],
        },
        headers=headers,
    ).json()
    leg_id = executed["transactions"][0]["id"]

    response = client.patch(
        f"/api/v1/transactions/{leg_id}", json={"description": "Bonifico mensile"}, headers=headers
    )

    # Doesn't feed the pairing, so it stays free — same rule as a portfolio
    # cash leg.
    assert response.status_code == 200, response.text


def test_an_unlinked_transfer_deletes_on_its_own(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    # An opening balance is a `transfer` with no counterpart: the invariant
    # is "may have one", so this must still delete normally.
    _account(client, headers, "Conto", balance="500.00")
    listed = client.get("/api/v1/transactions", headers=headers).json()
    opening = listed["data"][0]
    assert opening["counterpart_transaction_id"] is None

    response = client.delete(f"/api/v1/transactions/{opening['id']}", headers=headers)

    assert response.status_code == 204
    assert _balances(client, headers)["Conto"] == Decimal("0")


TRANSFERS_URL = "/api/v1/transactions/transfers"


def test_manual_transfer_creates_two_linked_legs_and_moves_balances(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto", balance="1000.00")
    savings = _account(client, headers, "Risparmi")

    response = client.post(
        TRANSFERS_URL,
        json={
            "from_account_id": main["id"],
            "to_account_id": savings["id"],
            "amount": "300.00",
            "date": "2026-09-20",
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    outgoing, incoming = response.json()
    assert outgoing["account_id"] == main["id"]
    assert Decimal(outgoing["amount"]) == Decimal("-300.00")
    assert incoming["account_id"] == savings["id"]
    assert Decimal(incoming["amount"]) == Decimal("300.00")
    assert outgoing["counterpart_transaction_id"] == incoming["id"]
    assert incoming["counterpart_transaction_id"] == outgoing["id"]
    assert outgoing["description"] == "Giroconto"

    balances = _balances(client, headers)
    assert balances["Conto"] == Decimal("700.00")
    assert balances["Risparmi"] == Decimal("300.00")


def test_manual_transfer_rejects_same_account(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")

    response = client.post(
        TRANSFERS_URL,
        json={
            "from_account_id": main["id"],
            "to_account_id": main["id"],
            "amount": "10.00",
            "date": "2026-09-20",
        },
        headers=headers,
    )

    assert response.status_code == 422


def test_manual_transfer_rejects_cross_currency(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    usd = _account(client, headers, "Dollari", currency="USD")

    response = client.post(
        TRANSFERS_URL,
        json={
            "from_account_id": main["id"],
            "to_account_id": usd["id"],
            "amount": "10.00",
            "date": "2026-09-20",
        },
        headers=headers,
    )

    assert response.status_code == 422
    listed = client.get("/api/v1/transactions", headers=headers).json()
    assert listed["data"] == []


def test_manual_transfer_rejects_a_non_positive_amount(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")

    response = client.post(
        TRANSFERS_URL,
        json={
            "from_account_id": main["id"],
            "to_account_id": savings["id"],
            "amount": "-10.00",
            "date": "2026-09-20",
        },
        headers=headers,
    )

    assert response.status_code == 422


def _manual_transfer(client: TestClient, headers: dict, from_id: str, to_id: str) -> list[dict]:
    response = client.post(
        TRANSFERS_URL,
        json={
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount": "50.00",
            "date": "2026-09-20",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_merged_list_shows_a_giroconto_once(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")
    outgoing, _ = _manual_transfer(client, headers, main["id"], savings["id"])

    response = client.get(
        "/api/v1/transactions", params={"merge_transfer_legs": True}, headers=headers
    )

    body = response.json()
    assert body["meta"]["total_items"] == 1
    (row,) = body["data"]
    assert row["id"] == outgoing["id"]
    assert row["account_id"] == main["id"]
    assert row["counterpart_account_id"] == savings["id"]


def test_merged_list_keeps_unpaired_transfers(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    # An opening balance is a positive, unpaired transfer: only the incoming
    # leg of a *pair* is dropped.
    _account(client, headers, "Conto", balance="500.00")

    response = client.get(
        "/api/v1/transactions", params={"merge_transfer_legs": True}, headers=headers
    )

    (row,) = response.json()["data"]
    assert row["counterpart_account_id"] is None


def test_merged_list_filtered_by_destination_shows_the_incoming_leg(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")
    _, incoming = _manual_transfer(client, headers, main["id"], savings["id"])

    response = client.get(
        "/api/v1/transactions",
        params={"merge_transfer_legs": True, "account_id": savings["id"]},
        headers=headers,
    )

    (row,) = response.json()["data"]
    assert row["id"] == incoming["id"]
    assert row["counterpart_account_id"] == main["id"]


def test_unmerged_list_still_returns_both_legs(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")
    _manual_transfer(client, headers, main["id"], savings["id"])

    response = client.get("/api/v1/transactions", headers=headers)

    assert response.json()["meta"]["total_items"] == 2


def test_editing_a_legs_description_updates_its_counterpart(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")
    outgoing, incoming = _manual_transfer(client, headers, main["id"], savings["id"])

    response = client.patch(
        f"/api/v1/transactions/{outgoing['id']}",
        json={"description": "Fondo vacanze"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    other = client.get(f"/api/v1/transactions/{incoming['id']}", headers=headers).json()
    assert other["description"] == "Fondo vacanze"


def _transfer_category(client: TestClient, headers: dict, name: str = "Risparmio") -> dict:
    response = client.post(
        "/api/v1/categories", json={"name": name, "type": "transfer"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_transfer_puts_its_category_on_both_legs(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")
    category = _transfer_category(client, headers)

    response = client.post(
        TRANSFERS_URL,
        json={
            "from_account_id": main["id"],
            "to_account_id": savings["id"],
            "category_id": category["id"],
            "amount": "50.00",
            "date": "2026-09-20",
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert [leg["category_id"] for leg in response.json()] == [category["id"]] * 2


def test_manual_transfer_without_category_is_not_put_in_varie(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")

    legs = _manual_transfer(client, headers, main["id"], savings["id"])

    assert [leg["category_id"] for leg in legs] == [None, None]


def test_manual_transfer_rejects_an_expense_category(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")
    expense = client.post(
        "/api/v1/categories", json={"name": "Spesa", "type": "expense"}, headers=headers
    ).json()

    response = client.post(
        TRANSFERS_URL,
        json={
            "from_account_id": main["id"],
            "to_account_id": savings["id"],
            "category_id": expense["id"],
            "amount": "50.00",
            "date": "2026-09-20",
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert client.get("/api/v1/transactions", headers=headers).json()["data"] == []


def test_editing_a_legs_category_updates_its_counterpart(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    main = _account(client, headers, "Conto")
    savings = _account(client, headers, "Risparmi")
    category = _transfer_category(client, headers)
    outgoing, incoming = _manual_transfer(client, headers, main["id"], savings["id"])

    response = client.patch(
        f"/api/v1/transactions/{outgoing['id']}",
        json={"category_id": category["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    other = client.get(f"/api/v1/transactions/{incoming['id']}", headers=headers).json()
    assert other["category_id"] == category["id"]

    # Clearing it clears both too — and a transfer is never pushed into Varie.
    client.patch(
        f"/api/v1/transactions/{outgoing['id']}", json={"category_id": None}, headers=headers
    )
    other = client.get(f"/api/v1/transactions/{incoming['id']}", headers=headers).json()
    assert other["category_id"] is None
