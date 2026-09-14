"""
Tests for the necessity taxonomy (phase A of the planning engine): the
domain rules on the two new fields, and the inheritance/aggregation logic
in `app.services.necessity`.

The service is exercised directly against the test session rather than
through HTTP, since phase A ships no endpoint that reads it yet — the
allocation status in phase B is its first consumer. Everything it reads is
still created through the API, so the rows look exactly like production's.
"""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.services.necessity import (
    UNCLASSIFIED,
    classification_coverage,
    income_by_category,
    income_total,
    spend_by_necessity,
)

PERIOD_FROM = date(2026, 9, 1)
PERIOD_TO = date(2026, 9, 30)


def _create_category(
    client: TestClient,
    headers: dict,
    name: str,
    category_type: str,
    parent_id: str | None = None,
    necessity_level: str | None = None,
    excluded_from_income_base: bool | None = None,
) -> dict:
    payload: dict = {"name": name, "type": category_type}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    if necessity_level is not None:
        payload["necessity_level"] = necessity_level
    if excluded_from_income_base is not None:
        payload["excluded_from_income_base"] = excluded_from_income_base
    response = client.post("/api/v1/categories", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _create_account(client: TestClient, headers: dict, name: str = "Main") -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": "checking", "currency": "EUR"},
        headers=headers,
    )
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
    necessity_level_override: str | None = None,
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
    if necessity_level_override is not None:
        payload["necessity_level_override"] = necessity_level_override
    response = client.post("/api/v1/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _current_user(db_session: Session) -> User:
    return db_session.query(User).one()


# ---------------------------------------------------------------------------
# Domain rules on the new fields
# ---------------------------------------------------------------------------

def test_necessity_level_rejected_on_income_category(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        "/api/v1/categories",
        json={"name": "Salary", "type": "income", "necessity_level": "primary"},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422


def test_excluded_from_income_base_rejected_on_expense_category(
    client: TestClient, registered_user: dict
) -> None:
    response = client.post(
        "/api/v1/categories",
        json={"name": "Food", "type": "expense", "excluded_from_income_base": True},
        headers=registered_user["auth_headers"],
    )

    assert response.status_code == 422


def test_necessity_level_can_be_cleared_back_to_null(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    category = _create_category(client, headers, "Food", "expense", necessity_level="primary")

    response = client.patch(
        f"/api/v1/categories/{category['id']}",
        json={"necessity_level": None},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["necessity_level"] is None


def test_necessity_override_rejected_on_income_transaction(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)

    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "amount": "1000.00",
            "currency": "EUR",
            "date": "2026-09-10",
            "type": "income",
            "necessity_level_override": "primary",
        },
        headers=headers,
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------

def test_subcategory_inherits_parent_necessity_level(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    parent = _create_category(client, headers, "Casa", "expense", necessity_level="primary")
    child = _create_category(client, headers, "Affitto", "expense", parent["id"])

    _create_transaction(client, headers, account["id"], "-800.00", "2026-09-05", child["id"])

    buckets = spend_by_necessity(
        db_session, _current_user(db_session), date_from=PERIOD_FROM, date_to=PERIOD_TO
    )

    assert buckets == {"primary": Decimal("800.00")}


def test_subcategory_own_level_overrides_parent(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    parent = _create_category(client, headers, "Casa", "expense", necessity_level="primary")
    child = _create_category(
        client, headers, "Arredamento", "expense", parent["id"], necessity_level="discretionary"
    )

    _create_transaction(client, headers, account["id"], "-300.00", "2026-09-05", child["id"])

    buckets = spend_by_necessity(
        db_session, _current_user(db_session), date_from=PERIOD_FROM, date_to=PERIOD_TO
    )

    assert buckets == {"discretionary": Decimal("300.00")}


def test_transaction_override_beats_category_and_parent(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    parent = _create_category(client, headers, "Svago", "expense", necessity_level="discretionary")
    child = _create_category(
        client, headers, "Ristoranti", "expense", parent["id"], necessity_level="useful"
    )

    # A work dinner filed under "Ristoranti" — the exception the override exists for.
    _create_transaction(
        client,
        headers,
        account["id"],
        "-120.00",
        "2026-09-12",
        child["id"],
        necessity_level_override="primary",
    )

    buckets = spend_by_necessity(
        db_session, _current_user(db_session), date_from=PERIOD_FROM, date_to=PERIOD_TO
    )

    assert buckets == {"primary": Decimal("120.00")}


def test_unclassified_spend_is_its_own_bucket_not_primary(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    category = _create_category(client, headers, "Food", "expense")

    _create_transaction(client, headers, account["id"], "-50.00", "2026-09-05", category["id"])

    buckets = spend_by_necessity(
        db_session, _current_user(db_session), date_from=PERIOD_FROM, date_to=PERIOD_TO
    )

    assert buckets == {UNCLASSIFIED: Decimal("50.00")}
    assert "primary" not in buckets


# ---------------------------------------------------------------------------
# Transfers must never read as spend
# ---------------------------------------------------------------------------

def test_opening_balance_transfer_is_excluded_from_every_bucket(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    # `starting_balance` creates a `transfer` row with category_id = NULL.
    # Without the type filter it would surface as a huge unclassified expense.
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Main",
            "type": "checking",
            "currency": "EUR",
            "starting_balance": "5000.00",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text

    buckets = spend_by_necessity(
        db_session,
        _current_user(db_session),
        date_from=date(2020, 1, 1),
        date_to=date(2030, 12, 31),
    )

    assert buckets == {}


def test_manual_transfer_is_excluded_from_buckets_and_income(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)

    _create_transaction(
        client, headers, account["id"], "-400.00", "2026-09-08", txn_type="transfer"
    )
    _create_transaction(
        client, headers, account["id"], "400.00", "2026-09-08", txn_type="transfer"
    )

    user = _current_user(db_session)
    buckets = spend_by_necessity(db_session, user, date_from=PERIOD_FROM, date_to=PERIOD_TO)
    income = income_total(db_session, user, date_from=PERIOD_FROM, date_to=PERIOD_TO)

    assert buckets == {}
    assert income == Decimal("0")


# ---------------------------------------------------------------------------
# Income base
# ---------------------------------------------------------------------------

def test_income_total_sums_income_in_period(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")

    _create_transaction(client, headers, account["id"], "2000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "500.00", "2026-09-20", salary["id"])
    # Outside the period — must not count.
    _create_transaction(client, headers, account["id"], "999.00", "2026-08-20", salary["id"])

    income = income_total(
        db_session, _current_user(db_session), date_from=PERIOD_FROM, date_to=PERIOD_TO
    )

    assert income == Decimal("2500.00")


def test_excluded_category_is_left_out_of_the_income_base(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")
    # The CSV-import case: a refund arrives typed as income purely by sign.
    refunds = _create_category(
        client, headers, "Rimborsi", "income", excluded_from_income_base=True
    )

    _create_transaction(client, headers, account["id"], "2000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "350.00", "2026-09-11", refunds["id"])

    income = income_total(
        db_session, _current_user(db_session), date_from=PERIOD_FROM, date_to=PERIOD_TO
    )

    assert income == Decimal("2000.00")


def test_income_by_category_still_reports_excluded_rows(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    refunds = _create_category(
        client, headers, "Rimborsi", "income", excluded_from_income_base=True
    )

    _create_transaction(client, headers, account["id"], "350.00", "2026-09-11", refunds["id"])

    rows = income_by_category(
        db_session, _current_user(db_session), date_from=PERIOD_FROM, date_to=PERIOD_TO
    )

    # Visible in the breakdown but flagged — that is what lets a user notice
    # an inflated denominator and opt the category out.
    assert len(rows) == 1
    assert rows[0]["category_name"] == "Rimborsi"
    assert rows[0]["excluded_from_income_base"] is True
    assert rows[0]["total_amount_base_currency"] == Decimal("350.00")


def test_negative_income_is_clamped_to_zero(
    client: TestClient, registered_user: dict, db_session: Session
) -> None:
    headers = registered_user["auth_headers"]
    account = _create_account(client, headers)
    salary = _create_category(client, headers, "Stipendio", "income")

    # Nothing validates sign against type, so a salary reversal booked as
    # negative income is one POST away. A negative base would make the
    # waterfall propose transfers in reverse.
    _create_transaction(client, headers, account["id"], "1000.00", "2026-09-01", salary["id"])
    _create_transaction(client, headers, account["id"], "-1500.00", "2026-09-02", salary["id"],
                        txn_type="income")

    income = income_total(
        db_session, _current_user(db_session), date_from=PERIOD_FROM, date_to=PERIOD_TO
    )

    assert income == Decimal("0")


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def test_classification_coverage_reports_share_of_classified_spend() -> None:
    buckets = {
        "primary": Decimal("600.00"),
        "discretionary": Decimal("200.00"),
        UNCLASSIFIED: Decimal("200.00"),
    }

    assert classification_coverage(buckets) == 80.0


def test_classification_coverage_of_no_spend_is_zero() -> None:
    assert classification_coverage({}) == 0.0
