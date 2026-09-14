"""
Tests for the budgets router: CRUD, category-type validation, and the
period-status calculation (current + historical, monthly bounds, over-budget).
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def eur_account(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Main checking", "type": "checking", "currency": "EUR"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def food_category(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/categories",
        json={"name": "Food", "type": "expense"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def income_category(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/categories",
        json={"name": "Salary", "type": "income"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_transaction(
    client: TestClient,
    headers: dict,
    account_id: str,
    category_id: str | None,
    amount: str,
    txn_date: str,
) -> dict:
    payload = {
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
    return response.json()


def test_create_budget_on_expense_category(
    client: TestClient, registered_user: dict, food_category: dict
) -> None:
    response = client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["category_id"] == food_category["id"]
    assert Decimal(body["amount_limit"]) == Decimal("200.00")


def test_create_budget_on_income_category_rejected(
    client: TestClient, registered_user: dict, income_category: dict
) -> None:
    response = client.post(
        "/api/v1/budgets",
        json={
            "category_id": income_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422


def test_list_budgets(client: TestClient, registered_user: dict, food_category: dict) -> None:
    client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=registered_user["auth_headers"],
    )

    response = client.get("/api/v1/budgets", headers=registered_user["auth_headers"])
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_budget_by_id(client: TestClient, registered_user: dict, food_category: dict) -> None:
    create_response = client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=registered_user["auth_headers"],
    )
    budget_id = create_response.json()["id"]

    response = client.get(f"/api/v1/budgets/{budget_id}", headers=registered_user["auth_headers"])
    assert response.status_code == 200
    assert response.json()["id"] == budget_id


def test_get_budget_not_found(client: TestClient, registered_user: dict) -> None:
    response = client.get(
        "/api/v1/budgets/00000000-0000-0000-0000-000000000000",
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 404


def test_delete_budget_is_soft_delete(
    client: TestClient, registered_user: dict, food_category: dict
) -> None:
    create_response = client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=registered_user["auth_headers"],
    )
    budget_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/budgets/{budget_id}", headers=registered_user["auth_headers"]
    )
    assert delete_response.status_code == 204

    list_response = client.get("/api/v1/budgets", headers=registered_user["auth_headers"])
    ids = [b["id"] for b in list_response.json()]
    assert budget_id not in ids


def test_status_computes_spent_within_current_month(
    client: TestClient, registered_user: dict, eur_account: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=headers,
    )

    _create_transaction(
        client, headers, eur_account["id"], food_category["id"], "-50.00", "2026-09-10"
    )
    _create_transaction(
        client, headers, eur_account["id"], food_category["id"], "-30.00", "2026-09-20"
    )

    response = client.get("/api/v1/budgets/status?date=2026-09-25", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert Decimal(body[0]["amount_spent"]) == Decimal("80.00")
    assert Decimal(body[0]["amount_limit"]) == Decimal("200.00")
    assert body[0]["percentage_used"] == 40.0
    assert body[0]["is_over_budget"] is False


def test_status_flags_over_budget(
    client: TestClient, registered_user: dict, eur_account: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "50.00",
            "start_date": "2026-09-01",
        },
        headers=headers,
    )

    _create_transaction(
        client, headers, eur_account["id"], food_category["id"], "-75.00", "2026-09-05"
    )

    response = client.get("/api/v1/budgets/status?date=2026-09-25", headers=headers)
    body = response.json()
    assert body[0]["is_over_budget"] is True
    assert Decimal(body[0]["amount_spent"]) == Decimal("75.00")


def test_status_excludes_transactions_outside_the_period(
    client: TestClient, registered_user: dict, eur_account: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-08-01",
        },
        headers=headers,
    )

    # One transaction in August, one in September.
    _create_transaction(
        client, headers, eur_account["id"], food_category["id"], "-40.00", "2026-08-15"
    )
    _create_transaction(
        client, headers, eur_account["id"], food_category["id"], "-60.00", "2026-09-15"
    )

    # Asking for August's status should only count the August transaction.
    response = client.get("/api/v1/budgets/status?date=2026-08-20", headers=headers)
    body = response.json()
    assert Decimal(body[0]["amount_spent"]) == Decimal("40.00")

    # Asking for September's status should only count the September one.
    response = client.get("/api/v1/budgets/status?date=2026-09-20", headers=headers)
    body = response.json()
    assert Decimal(body[0]["amount_spent"]) == Decimal("60.00")


def test_status_defaults_to_zero_spent_with_no_transactions(
    client: TestClient, registered_user: dict, food_category: dict
) -> None:
    client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=registered_user["auth_headers"],
    )

    response = client.get(
        "/api/v1/budgets/status?date=2026-09-15", headers=registered_user["auth_headers"]
    )
    body = response.json()
    assert Decimal(body[0]["amount_spent"]) == Decimal("0")
    assert body[0]["percentage_used"] == 0.0


def test_transaction_without_category_defaults_to_varie(
    client: TestClient, registered_user: dict, eur_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "amount": "-20.00",
            "currency": "EUR",
            "date": "2026-09-10",
            "type": "expense",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    transaction = response.json()
    assert transaction["category_id"] is not None

    categories_response = client.get("/api/v1/categories", headers=headers)
    categories = categories_response.json()
    misc = next(c for c in categories if c["id"] == transaction["category_id"])
    assert misc["name"] == "Varie"
    assert misc["type"] == "expense"


def test_transaction_without_category_reuses_existing_varie(
    client: TestClient, registered_user: dict, eur_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    first = client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "amount": "-10.00",
            "currency": "EUR",
            "date": "2026-09-01",
            "type": "expense",
        },
        headers=headers,
    ).json()

    second = client.post(
        "/api/v1/transactions",
        json={
            "account_id": eur_account["id"],
            "amount": "-15.00",
            "currency": "EUR",
            "date": "2026-09-02",
            "type": "expense",
        },
        headers=headers,
    ).json()

    # Same "Varie" category reused, not duplicated on every uncategorized transaction.
    assert first["category_id"] == second["category_id"]

# ---------------------------------------------------------------------------
# Subcategory roll-up and one-budget-per-category
# ---------------------------------------------------------------------------

def _create_subcategory(client: TestClient, headers: dict, name: str, parent_id: str) -> dict:
    response = client.post(
        "/api/v1/categories",
        json={"name": name, "type": "expense", "parent_id": parent_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_budget_on_a_parent_counts_subcategory_spend(
    client: TestClient, registered_user: dict, eur_account: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    restaurants = _create_subcategory(client, headers, "Restaurants", food_category["id"])

    client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=headers,
    )
    # Filed on the child, budgeted on the parent.
    _create_transaction(
        client, headers, eur_account["id"], restaurants["id"], "-150.00", "2026-09-10"
    )

    response = client.get("/api/v1/budgets/status?date=2026-09-25", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body[0]["amount_spent"]) == Decimal("150.00")


def test_budget_on_a_subcategory_does_not_count_its_parent(
    client: TestClient, registered_user: dict, eur_account: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    # Spend filed on the category while it was still childless — the only
    # way a parent can carry spend of its own, since a transaction can't be
    # assigned to a category that already has subcategories.
    _create_transaction(
        client, headers, eur_account["id"], food_category["id"], "-80.00", "2026-09-10"
    )
    restaurants = _create_subcategory(client, headers, "Restaurants", food_category["id"])

    client.post(
        "/api/v1/budgets",
        json={
            "category_id": restaurants["id"],
            "period": "monthly",
            "amount_limit": "100.00",
            "start_date": "2026-09-01",
        },
        headers=headers,
    )

    body = client.get("/api/v1/budgets/status?date=2026-09-25", headers=headers).json()

    # Roll-up goes downward only: the parent's own legacy spend is not the
    # child's, or every sibling budget would inherit it.
    assert Decimal(body[0]["amount_spent"]) == Decimal("0")


def test_second_budget_on_the_same_category_is_rejected(
    client: TestClient, registered_user: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    payload = {
        "category_id": food_category["id"],
        "period": "monthly",
        "amount_limit": "200.00",
        "start_date": "2026-09-01",
    }
    first = client.post("/api/v1/budgets", json=payload, headers=headers)
    assert first.status_code == 201, first.text

    second = client.post("/api/v1/budgets", json=payload, headers=headers)

    assert second.status_code == 409


def test_same_category_can_hold_a_monthly_and_a_yearly_budget(
    client: TestClient, registered_user: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    base = {
        "category_id": food_category["id"],
        "amount_limit": "200.00",
        "start_date": "2026-09-01",
    }

    monthly = client.post("/api/v1/budgets", json={**base, "period": "monthly"}, headers=headers)
    yearly = client.post("/api/v1/budgets", json={**base, "period": "yearly"}, headers=headers)

    assert monthly.status_code == 201, monthly.text
    assert yearly.status_code == 201, yearly.text


def test_a_deleted_budget_frees_the_category_again(
    client: TestClient, registered_user: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    payload = {
        "category_id": food_category["id"],
        "period": "monthly",
        "amount_limit": "200.00",
        "start_date": "2026-09-01",
    }
    created = client.post("/api/v1/budgets", json=payload, headers=headers).json()
    client.delete(f"/api/v1/budgets/{created['id']}", headers=headers)

    # The unique index is partial on deleted_at IS NULL, so recreating is
    # how a user effectively edits a budget's frozen fields.
    recreated = client.post("/api/v1/budgets", json=payload, headers=headers)

    assert recreated.status_code == 201, recreated.text


def test_status_exposes_the_budget_id(
    client: TestClient, registered_user: dict, food_category: dict
) -> None:
    headers = registered_user["auth_headers"]
    created = client.post(
        "/api/v1/budgets",
        json={
            "category_id": food_category["id"],
            "period": "monthly",
            "amount_limit": "200.00",
            "start_date": "2026-09-01",
        },
        headers=headers,
    ).json()

    body = client.get("/api/v1/budgets/status?date=2026-09-25", headers=headers).json()

    assert body[0]["budget_id"] == created["id"]
