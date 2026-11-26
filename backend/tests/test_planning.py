"""
Tests for the planning engine's phase B: the allocation plan, the status
of the current period against it, the survival budget, and the simulator.

Dates are hardcoded in 2026 so the `?date=` parameter is deterministic —
same convention as test_budgets.py. The averages deliberately look at
*complete* months only, so fixtures place history in months strictly
before the month under test.
"""

from decimal import Decimal

from fastapi.testclient import TestClient

PLAN_URL = "/api/v1/planning/plan"
STATUS_URL = "/api/v1/planning/allocation-status"
SURVIVAL_URL = "/api/v1/planning/survival-budget"
SIMULATE_URL = "/api/v1/planning/simulate"


def _create_account(client: TestClient, headers: dict, name: str = "Conto") -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": "checking", "currency": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_category(
    client: TestClient,
    headers: dict,
    name: str,
    category_type: str,
    necessity_level: str | None = None,
    excluded_from_income_base: bool | None = None,
) -> dict:
    payload: dict = {"name": name, "type": category_type}
    if necessity_level is not None:
        payload["necessity_level"] = necessity_level
    if excluded_from_income_base is not None:
        payload["excluded_from_income_base"] = excluded_from_income_base
    response = client.post("/api/v1/categories", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _create_transaction(
    client: TestClient,
    headers: dict,
    account_id: str,
    amount: str,
    txn_date: str,
    category_id: str | None = None,
    txn_type: str | None = None,
) -> dict:
    payload: dict = {
        "account_id": account_id,
        "amount": amount,
        "currency": "EUR",
        "date": txn_date,
        "type": txn_type or ("expense" if Decimal(amount) < 0 else "income"),
    }
    if category_id is not None:
        payload["category_id"] = category_id
    response = client.post("/api/v1/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _bucket(body: dict, name: str) -> dict:
    return next(b for b in body["buckets"] if b["bucket"] == name)


# ---------------------------------------------------------------------------
# The plan itself
# ---------------------------------------------------------------------------

def test_plan_is_created_with_the_preset_on_first_read(
    client: TestClient, registered_user: dict
) -> None:
    response = client.get(PLAN_URL, headers=registered_user["auth_headers"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["pct_primary"]) == Decimal("50")
    assert Decimal(body["pct_useful"]) == Decimal("25")
    assert Decimal(body["pct_discretionary"]) == Decimal("15")
    assert Decimal(body["pct_savings"]) == Decimal("10")
    assert body["lookback_months"] == 6


def test_reading_the_plan_twice_returns_the_same_row(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    first = client.get(PLAN_URL, headers=headers).json()
    second = client.get(PLAN_URL, headers=headers).json()

    assert first["id"] == second["id"]


def test_partial_percentage_update_is_rejected(
    client: TestClient, registered_user: dict
) -> None:
    # The four percentages are constrained to sum to 100 in the database,
    # so a partial update could only ever fail — better a 422 that says so.
    response = client.patch(
        PLAN_URL, json={"pct_primary": "60"}, headers=registered_user["auth_headers"]
    )

    assert response.status_code == 422


def test_percentages_not_summing_to_100_are_rejected(
    client: TestClient, registered_user: dict
) -> None:
    response = client.patch(
        PLAN_URL,
        json={
            "pct_primary": "60",
            "pct_useful": "25",
            "pct_discretionary": "15",
            "pct_savings": "10",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422


def test_percentages_can_be_changed_together(client: TestClient, registered_user: dict) -> None:
    response = client.patch(
        PLAN_URL,
        json={
            "pct_primary": "60",
            "pct_useful": "20",
            "pct_discretionary": "10",
            "pct_savings": "10",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 200, response.text
    assert Decimal(response.json()["pct_primary"]) == Decimal("60")


def test_source_account_must_belong_to_the_user(
    client: TestClient, registered_user: dict
) -> None:
    response = client.patch(
        PLAN_URL,
        json={"default_source_account_id": "00000000-0000-0000-0000-000000000000"},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Allocation status
# ---------------------------------------------------------------------------

def test_status_splits_income_by_the_plan_percentages(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    casa = _create_category(client, headers, "Casa", "expense", necessity_level="primary")

    _create_transaction(client, headers, account["id"], "2000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "-900.00", "2026-09-05", casa["id"])

    response = client.get(f"{STATUS_URL}?date=2026-09-20", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["income_total"]) == Decimal("2000.00")

    primary = _bucket(body, "primary")
    assert Decimal(primary["target_amount"]) == Decimal("1000.00")  # 50% of 2000
    assert Decimal(primary["actual_amount"]) == Decimal("900.00")
    assert Decimal(primary["deviation"]) == Decimal("100.00")
    assert primary["is_over_target"] is False

    # Savings is the residual: 2000 earned - 900 spent.
    savings = _bucket(body, "savings")
    assert Decimal(savings["target_amount"]) == Decimal("200.00")
    assert Decimal(savings["actual_amount"]) == Decimal("1100.00")


def test_status_flags_a_bucket_over_target(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    svago = _create_category(client, headers, "Svago", "expense", necessity_level="discretionary")

    _create_transaction(client, headers, account["id"], "1000.00", "2026-09-01", salary["id"])
    # 15% of 1000 is 150; spending 400 is well over.
    _create_transaction(client, headers, account["id"], "-400.00", "2026-09-07", svago["id"])

    body = client.get(f"{STATUS_URL}?date=2026-09-20", headers=headers).json()
    discretionary = _bucket(body, "discretionary")

    assert Decimal(discretionary["actual_amount"]) == Decimal("400.00")
    assert discretionary["is_over_target"] is True


def test_status_excludes_transfers_from_income(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")

    _create_transaction(client, headers, account["id"], "1000.00", "2026-09-01", salary["id"])
    _create_transaction(
        client, headers, account["id"], "5000.00", "2026-09-02", txn_type="transfer"
    )

    body = client.get(f"{STATUS_URL}?date=2026-09-20", headers=headers).json()

    assert Decimal(body["income_total"]) == Decimal("1000.00")


def test_status_excludes_opted_out_income_categories(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    refunds = _create_category(
        client, headers, "Rimborsi", "income", excluded_from_income_base=True
    )

    _create_transaction(client, headers, account["id"], "2000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "500.00", "2026-09-03", refunds["id"])

    body = client.get(f"{STATUS_URL}?date=2026-09-20", headers=headers).json()

    assert Decimal(body["income_total"]) == Decimal("2000.00")
    # Still visible in the breakdown, flagged — that is how a user notices.
    excluded = next(r for r in body["income_breakdown"] if r["excluded_from_income_base"])
    assert Decimal(excluded["total_amount_base_currency"]) == Decimal("500.00")


def test_status_reports_unclassified_spend_separately(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    classified = _create_category(client, headers, "Casa", "expense", necessity_level="primary")
    unclassified = _create_category(client, headers, "Varie spese", "expense")

    _create_transaction(client, headers, account["id"], "1000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "-300.00", "2026-09-05", classified["id"])
    _create_transaction(client, headers, account["id"], "-100.00", "2026-09-06", unclassified["id"])

    body = client.get(f"{STATUS_URL}?date=2026-09-20", headers=headers).json()

    assert Decimal(body["unclassified_amount"]) == Decimal("100.00")
    assert body["classification_coverage"] == 75.0
    # The unclassified 100 must not have leaked into primary.
    assert Decimal(_bucket(body, "primary")["actual_amount"]) == Decimal("300.00")


def test_status_with_zero_income_does_not_divide_by_zero(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    casa = _create_category(client, headers, "Casa", "expense", necessity_level="primary")
    _create_transaction(client, headers, account["id"], "-200.00", "2026-09-05", casa["id"])

    response = client.get(f"{STATUS_URL}?date=2026-09-20", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["income_total"]) == Decimal("0.00")
    primary = _bucket(body, "primary")
    assert Decimal(primary["target_amount"]) == Decimal("0.00")
    assert primary["percentage_used"] == 0.0


def test_status_clamps_negative_income_to_zero(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")

    _create_transaction(client, headers, account["id"], "1000.00", "2026-09-01", salary["id"])
    # A salary reversal: nothing validates sign against type.
    _create_transaction(
        client, headers, account["id"], "-1500.00", "2026-09-02", salary["id"], txn_type="income"
    )

    body = client.get(f"{STATUS_URL}?date=2026-09-20", headers=headers).json()

    assert Decimal(body["income_total"]) == Decimal("0.00")


def test_status_uses_the_updated_percentages(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    _create_transaction(client, headers, account["id"], "1000.00", "2026-09-01", salary["id"])

    client.patch(
        PLAN_URL,
        json={
            "pct_primary": "70",
            "pct_useful": "10",
            "pct_discretionary": "10",
            "pct_savings": "10",
        },
        headers=headers,
    )

    body = client.get(f"{STATUS_URL}?date=2026-09-20", headers=headers).json()

    assert Decimal(_bucket(body, "primary")["target_amount"]) == Decimal("700.00")


# ---------------------------------------------------------------------------
# Survival budget
# ---------------------------------------------------------------------------

def test_survival_budget_averages_complete_months_only(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    casa = _create_category(client, headers, "Casa", "expense", necessity_level="primary")

    # Three complete months before September: 600 + 800 + 700 = 2100 / 3 = 700.
    _create_transaction(client, headers, account["id"], "-600.00", "2026-06-10", casa["id"])
    _create_transaction(client, headers, account["id"], "-800.00", "2026-07-10", casa["id"])
    _create_transaction(client, headers, account["id"], "-700.00", "2026-08-10", casa["id"])
    # September is still in progress and must be ignored entirely.
    _create_transaction(client, headers, account["id"], "-50.00", "2026-09-02", casa["id"])

    response = client.get(f"{SURVIVAL_URL}?date=2026-09-14", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["months_analysed"] == 3
    assert Decimal(body["monthly_primary_expenses"]) == Decimal("700.00")


def test_survival_budget_is_unavailable_without_a_complete_month(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    casa = _create_category(client, headers, "Casa", "expense", necessity_level="primary")
    _create_transaction(client, headers, account["id"], "-400.00", "2026-09-03", casa["id"])

    body = client.get(f"{SURVIVAL_URL}?date=2026-09-14", headers=headers).json()

    # None, not zero: zero would read as "you need nothing to live on", and
    # in phase C would mark a dynamic emergency-fund target as already met.
    assert body["monthly_primary_expenses"] is None
    assert body["months_analysed"] == 0
    assert body["months_of_runway"] is None


def test_survival_budget_counts_months_with_no_primary_spend(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    casa = _create_category(client, headers, "Casa", "expense", necessity_level="primary")

    # History starts in June; July and August had no primary spend at all,
    # and those zeros are real data that must lower the average.
    _create_transaction(client, headers, account["id"], "-900.00", "2026-06-10", casa["id"])

    body = client.get(f"{SURVIVAL_URL}?date=2026-09-14", headers=headers).json()

    assert body["months_analysed"] == 3
    assert Decimal(body["monthly_primary_expenses"]) == Decimal("300.00")


def test_survival_budget_reports_months_of_runway(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Conto",
            "type": "checking",
            "currency": "EUR",
            "starting_balance": "3000.00",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    account = response.json()
    casa = _create_category(client, headers, "Casa", "expense", necessity_level="primary")
    _create_transaction(client, headers, account["id"], "-500.00", "2026-08-10", casa["id"])

    body = client.get(f"{SURVIVAL_URL}?date=2026-09-14", headers=headers).json()

    # Cash is 3000 opening balance less the 500 expense = 2500.
    assert Decimal(body["total_cash_balance"]) == Decimal("2500.00")
    assert Decimal(body["monthly_primary_expenses"]) == Decimal("500.00")
    assert body["months_of_runway"] == 5.0


def _funded_account(
    client: TestClient, headers: dict, name: str, balance: str, type_: str = "checking"
) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": type_, "currency": "EUR", "starting_balance": balance},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _goal_on(client: TestClient, headers: dict, account_id: str, **goal) -> dict:
    response = client.post("/api/v1/planning/goals", json=goal, headers=headers)
    assert response.status_code == 201, response.text
    created = response.json()
    response = client.post(
        f"/api/v1/planning/goals/{created['id']}/sources",
        json={"account_id": account_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return created


def test_runway_lives_off_operating_cash_and_the_emergency_fund_only(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    current = _funded_account(client, headers, "Corrente", "2000.00")
    emergency = _funded_account(client, headers, "Emergenza", "3000.00", "savings")
    house = _funded_account(client, headers, "Casa", "10000.00", "savings")
    _funded_account(client, headers, "Broker", "4000.00", "investment")
    taxes = _funded_account(client, headers, "Tasse", "1500.00", "savings")
    _goal_on(
        client, headers, emergency["id"],
        name="Fondo emergenza", kind="emergency_fund",
        target_mode="fixed_amount", target_amount="2500.00",
    )
    _goal_on(
        client, headers, house["id"],
        name="Anticipo casa", kind="medium_term",
        target_mode="fixed_amount", target_amount="20000.00",
    )
    response = client.post(
        "/api/v1/flat-rate/sources", json={"account_id": taxes["id"]}, headers=headers
    )
    assert response.status_code == 201, response.text
    casa = _create_category(client, headers, "Affitto", "expense", necessity_level="primary")
    _create_transaction(client, headers, current["id"], "-500.00", "2026-08-10", casa["id"])

    body = client.get(f"{SURVIVAL_URL}?date=2026-09-14", headers=headers).json()

    # Current 1500 + emergency fund 2500 + the 500 its account holds above
    # the target. The down payment, the broker's cash and the tax provision
    # all have another job.
    assert Decimal(body["operating_cash"]) == Decimal("1500.00")
    assert Decimal(body["emergency_fund"]) == Decimal("2500.00")
    assert Decimal(body["goal_excess"]) == Decimal("500.00")
    assert Decimal(body["committed_outflows"]) == Decimal("0.00")
    assert Decimal(body["total_cash_balance"]) == Decimal("4500.00")
    assert body["months_of_runway"] == 9.0


def test_runway_subtracts_debits_scheduled_from_the_operating_accounts(
    client: TestClient, registered_user: dict
) -> None:
    from datetime import date, timedelta

    headers = registered_user["auth_headers"]
    current = _funded_account(client, headers, "Corrente", "3000.00")
    response = client.post(
        "/api/v1/flat-rate/payments",
        json={
            "status": "scheduled",
            "paid_on": (date.today() + timedelta(days=5)).isoformat(),
            "fiscal_year": 2025,
            "component": "substitute_tax",
            "kind": "balance",
            "amount": "500.00",
            "account_id": current["id"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    casa = _create_category(client, headers, "Affitto", "expense", necessity_level="primary")
    _create_transaction(client, headers, current["id"], "-500.00", "2026-08-10", casa["id"])

    body = client.get(f"{SURVIVAL_URL}?date=2026-09-14", headers=headers).json()

    # 2500 on the account, but 500 of it is already the State's F24.
    assert Decimal(body["committed_outflows"]) == Decimal("500.00")
    assert Decimal(body["total_cash_balance"]) == Decimal("2000.00")
    assert body["months_of_runway"] == 4.0


def test_an_overdraft_is_no_runway_not_negative_months(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    current = _funded_account(client, headers, "Corrente", "0")
    casa = _create_category(client, headers, "Affitto", "expense", necessity_level="primary")
    _create_transaction(client, headers, current["id"], "-500.00", "2026-08-10", casa["id"])

    body = client.get(f"{SURVIVAL_URL}?date=2026-09-14", headers=headers).json()

    assert Decimal(body["total_cash_balance"]) == Decimal("-500.00")
    assert body["months_of_runway"] == 0.0


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def test_simulate_frees_spend_from_a_bucket(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    svago = _create_category(client, headers, "Svago", "expense", necessity_level="discretionary")

    _create_transaction(client, headers, account["id"], "2000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "-400.00", "2026-09-05", svago["id"])

    response = client.post(
        SIMULATE_URL,
        json={"date": "2026-09-20", "cuts": [{"necessity_level": "discretionary",
                                              "cut_percentage": "50"}]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    discretionary = _bucket(body, "discretionary")
    assert Decimal(discretionary["baseline_amount"]) == Decimal("400.00")
    assert Decimal(discretionary["simulated_amount"]) == Decimal("200.00")
    assert Decimal(discretionary["freed_amount"]) == Decimal("200.00")
    assert Decimal(body["simulated_savings_amount"]) == Decimal("1800.00")


def test_simulate_category_cut_wins_over_bucket_cut(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    netflix = _create_category(
        client, headers, "Netflix", "expense", necessity_level="discretionary"
    )
    altro = _create_category(client, headers, "Altro svago", "expense",
                             necessity_level="discretionary")

    _create_transaction(client, headers, account["id"], "2000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "-100.00", "2026-09-05", netflix["id"])
    _create_transaction(client, headers, account["id"], "-200.00", "2026-09-06", altro["id"])

    response = client.post(
        SIMULATE_URL,
        json={
            "date": "2026-09-20",
            "cuts": [
                {"necessity_level": "discretionary", "cut_percentage": "50"},
                {"category_id": netflix["id"], "cut_percentage": "100"},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Netflix is cut 100% (100) and excluded from the bucket cut; the other
    # 200 is cut 50% (100). Total freed 200, not 250 — no double counting.
    assert Decimal(body["total_freed"]) == Decimal("200.00")


def test_simulate_rejects_a_cut_targeting_both_or_neither(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]

    neither = client.post(SIMULATE_URL, json={"cuts": [{"cut_percentage": "50"}]}, headers=headers)
    assert neither.status_code == 422

    category = _create_category(
        client, headers, "Svago", "expense", necessity_level="discretionary"
    )
    both = client.post(
        SIMULATE_URL,
        json={
            "cuts": [
                {
                    "necessity_level": "discretionary",
                    "category_id": category["id"],
                    "cut_percentage": "50",
                }
            ]
        },
        headers=headers,
    )
    assert both.status_code == 422


def test_simulate_rejects_duplicate_cuts_on_the_same_target(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        SIMULATE_URL,
        json={
            "cuts": [
                {"necessity_level": "useful", "cut_percentage": "10"},
                {"necessity_level": "useful", "cut_percentage": "90"},
            ]
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422


def test_simulate_rejects_a_cut_on_an_income_category(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    salary = _create_category(client, headers, "Stipendio", "income")

    response = client.post(
        SIMULATE_URL,
        json={"cuts": [{"category_id": salary["id"], "cut_percentage": "50"}]},
        headers=headers,
    )

    assert response.status_code == 422


def test_simulate_lowers_the_survival_budget_when_primary_is_cut(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    casa = _create_category(client, headers, "Casa", "expense", necessity_level="primary")

    # One complete month of history sets the baseline survival budget.
    _create_transaction(client, headers, account["id"], "-800.00", "2026-08-10", casa["id"])
    # The current period's primary spend is what the cut is applied to.
    _create_transaction(client, headers, account["id"], "-800.00", "2026-09-05", casa["id"])

    body = client.post(
        SIMULATE_URL,
        json={"date": "2026-09-20",
              "cuts": [{"necessity_level": "primary", "cut_percentage": "25"}]},
        headers=headers,
    ).json()

    assert Decimal(body["baseline_survival_budget"]) == Decimal("800.00")
    assert Decimal(body["simulated_survival_budget"]) == Decimal("600.00")


def test_simulate_with_no_cuts_changes_nothing(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    casa = _create_category(client, headers, "Casa", "expense", necessity_level="primary")
    _create_transaction(client, headers, account["id"], "1000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "-300.00", "2026-09-05", casa["id"])

    body = client.post(
        SIMULATE_URL, json={"date": "2026-09-20", "cuts": []}, headers=headers
    ).json()

    assert Decimal(body["total_freed"]) == Decimal("0.00")
    assert Decimal(body["baseline_savings_amount"]) == Decimal(body["simulated_savings_amount"])
    assert body["baseline_savings_rate"] == 70.0
