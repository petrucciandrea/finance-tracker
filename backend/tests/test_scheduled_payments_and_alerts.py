"""
The bollo as an F24 line (owed per invoice delivered, paid per quarter),
payments scheduled before they're taken, vehicle deadlines, and the alerts
built on top of them.

Pure computations run on a hand-built `Ledger`; the rest goes through the
API. Dates are in the past where the code reads "today", except where a
test needs a scheduled debit still to come.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.services import alerts as alerts_service
from app.services import flat_rate as service

URL = "/api/v1/flat-rate"
YEAR_ROW = service.YearRow(
    profitability_coefficient=Decimal("0.78"),
    substitute_tax_rate=Decimal("0.05"),
    inps_rate=Decimal("0.2623"),
    rivalsa_rate=Decimal("0.04"),
)


def _stamped(issue: date, delivered: date | None = None, collected: date | None = None):
    return SimpleNamespace(
        amount=Decimal("1000"),
        rivalsa_rate=Decimal("0"),
        stamp_duty=True,
        issue_date=issue,
        sdi_delivered_on=delivered,
        collected_on=collected,
        provision_rate=None,
    )


def _payment(amount: str, on: date, fiscal_year: int, component: str, kind: str):
    return SimpleNamespace(
        amount=Decimal(amount),
        paid_on=on,
        fiscal_year=fiscal_year,
        component=component,
        kind=kind,
    )


def _ledger(stamped=(), stamp_payments=(), scheduled=(), invoices=(), payments=()):
    return service.Ledger(
        invoices=list(invoices),
        payments=list(payments),
        params={y: YEAR_ROW for y in range(2024, 2030)},
        activity_start=None,
        safety_margin=Decimal("0.15"),
        stamped=list(stamped),
        stamp_payments=list(stamp_payments),
        scheduled=list(scheduled),
    )


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def test_deadlines_on_a_holiday_or_weekend_move_to_the_next_working_day() -> None:
    assert service.next_business_day(date(2026, 11, 30)) == date(2026, 11, 30)  # Monday
    assert service.next_business_day(date(2025, 11, 30)) == date(2025, 12, 1)  # Sunday
    # Saturday 31 May 2025, then Monday 2 June is the Festa della Repubblica.
    assert service.next_business_day(date(2025, 5, 31)) == date(2025, 6, 3)
    # Easter Monday 2026 is 6 April.
    assert not service.is_business_day(date(2026, 4, 6))


def test_a_freelancers_bollo_is_paid_in_november_and_february() -> None:
    small = {(2026, 1): Decimal("20"), (2026, 2): Decimal("30")}
    for quarter in (1, 2, 3):
        assert service.stamp_duty_due_date(2026, quarter, small) == date(2026, 11, 30)
    # 28 February 2027 is a Sunday.
    assert service.stamp_duty_due_date(2026, 4, small) == date(2027, 3, 1)


def test_a_large_bollo_keeps_its_own_quarter() -> None:
    large = {(2026, 1): Decimal("6000"), (2026, 2): Decimal("10")}
    assert service.stamp_duty_due_date(2026, 1, large) == date(2026, 6, 1)  # 31 May is Sunday
    assert service.stamp_duty_due_date(2026, 2, large) == date(2026, 9, 30)
    # Q1 alone under the limit, Q1 + Q2 over: Q1 goes with Q2.
    mixed = {(2026, 1): Decimal("3000"), (2026, 2): Decimal("3000")}
    assert service.stamp_duty_due_date(2026, 1, mixed) == date(2026, 9, 30)


# ---------------------------------------------------------------------------
# Bollo in the figures
# ---------------------------------------------------------------------------


def test_bollo_is_owed_from_delivery_whether_collected_or_not() -> None:
    ledger = _ledger(
        stamped=[
            _stamped(date(2026, 2, 10)),
            # Dated in March, delivered in April: a second-quarter one.
            _stamped(date(2026, 3, 30), delivered=date(2026, 4, 1)),
            _stamped(date(2026, 8, 1), collected=date(2026, 9, 1)),
        ]
    )
    quarters = service.stamp_duty_by_quarter(ledger)
    assert quarters == {
        (2026, 1): Decimal("2.00"),
        (2026, 2): Decimal("2.00"),
        (2026, 3): Decimal("2.00"),
    }
    assert service.stamp_duty_accrued(ledger, date(2026, 3, 31)) == Decimal("2.00")
    assert service.tax_liability(ledger, date(2026, 10, 1)) == Decimal("6.00")
    assert service.cash_requirement(ledger, date(2026, 10, 1)) == Decimal("6.00")


def test_paying_a_quarter_lowers_the_debt_and_the_deadline() -> None:
    ledger = _ledger(
        stamped=[_stamped(date(2026, 2, 10)), _stamped(date(2026, 2, 20))],
        stamp_payments=[_payment("4.00", date(2026, 11, 30), 2026, "stamp_duty", "q1")],
    )
    assert service.tax_liability(ledger, date(2026, 11, 29)) == Decimal("4.00")
    position = service.tax_position(ledger, date(2026, 12, 1))
    assert (position.debt, position.credit) == (Decimal("0"), Decimal("0"))

    rows = service.deadlines(ledger, 2026, date(2026, 12, 1))
    q1 = next(r for r in rows if r.component == "stamp_duty" and r.kind == "q1")
    assert (q1.due_date, q1.amount_due, q1.amount_paid) == (
        date(2026, 11, 30),
        Decimal("4.00"),
        Decimal("4.00"),
    )
    assert not q1.is_estimate


def test_a_scheduled_payment_counts_nowhere_but_next_to_its_deadline() -> None:
    scheduled = _payment("2.00", date(2026, 11, 30), 2026, "stamp_duty", "q3")
    ledger = _ledger(stamped=[_stamped(date(2026, 8, 1))], scheduled=[scheduled])
    assert service.tax_liability(ledger, date(2026, 12, 15)) == Decimal("2.00")
    q3 = next(r for r in service.deadlines(ledger, 2026, date(2026, 11, 25)) if r.kind == "q3")
    assert q3.amount_paid == Decimal("0")
    assert q3.amount_scheduled == Decimal("2.00")
    assert q3.scheduled_on == date(2026, 11, 30)
    assert q3.is_arranged


# ---------------------------------------------------------------------------
# API: scheduling and confirming
# ---------------------------------------------------------------------------


@pytest.fixture
def headers(registered_user: dict) -> dict:
    return registered_user["auth_headers"]


def _account(client: TestClient, headers: dict, name: str = "Conto", currency: str = "EUR") -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": "checking", "currency": currency},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _movement(client: TestClient, headers: dict, account_id: str, amount: str, on: str, type_: str):
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "amount": amount,
            "currency": "EUR",
            "date": on,
            "type": type_,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _net_worth(client: TestClient, headers: dict) -> dict:
    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _balance(client: TestClient, headers: dict, account_id: str) -> Decimal:
    accounts = _net_worth(client, headers)["accounts"]
    return Decimal(next(a["balance"] for a in accounts if a["account_id"] == account_id))


def _schedule(client: TestClient, headers: dict, account_id: str, **overrides) -> dict:
    payload = {
        "status": "scheduled",
        "paid_on": (date.today() + timedelta(days=5)).isoformat(),
        "fiscal_year": 2025,
        "component": "stamp_duty",
        "kind": "q3",
        "amount": "6.00",
        "account_id": account_id,
        **overrides,
    }
    response = client.post(f"{URL}/payments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_invoice_with_bollo_is_a_debt_until_its_quarter_is_paid(
    client: TestClient, headers: dict
) -> None:
    response = client.post(
        f"{URL}/invoices",
        json={"client": "Acme", "issue_date": "2025-08-01", "amount": "500.00"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["stamp_duty"] is True
    net_worth = _net_worth(client, headers)
    assert Decimal(net_worth["total_tax_liability"]) == Decimal("2.00")

    account = _account(client, headers)
    response = client.post(
        f"{URL}/payments",
        json={
            "paid_on": "2025-12-01",
            "fiscal_year": 2025,
            "component": "stamp_duty",
            "kind": "q3",
            "amount": "2.00",
            "account_id": account["id"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    after = _net_worth(client, headers)
    assert Decimal(after["total_tax_liability"]) == Decimal("0")
    assert Decimal(after["total_net_worth"]) == Decimal(net_worth["total_net_worth"])


def test_a_paid_payment_needs_the_account_it_left(client: TestClient, headers: dict) -> None:
    """Without one the debt would drop and no balance would: net worth would rise."""
    response = client.post(
        f"{URL}/payments",
        json={
            "paid_on": "2025-12-01",
            "fiscal_year": 2025,
            "component": "stamp_duty",
            "kind": "q3",
            "amount": "2.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_sdi_delivery_before_issue_is_refused(client: TestClient, headers: dict) -> None:
    response = client.post(
        f"{URL}/invoices",
        json={
            "client": "Acme",
            "issue_date": "2025-08-01",
            "sdi_delivered_on": "2025-07-31",
            "amount": "500.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_bollo_lines_are_paid_per_quarter(client: TestClient, headers: dict) -> None:
    account = _account(client, headers)
    response = client.post(
        f"{URL}/payments",
        json={
            "paid_on": "2025-12-01",
            "fiscal_year": 2025,
            "component": "stamp_duty",
            "kind": "balance",
            "amount": "2.00",
            "account_id": account["id"],
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_a_paid_payment_cannot_be_dated_ahead(client: TestClient, headers: dict) -> None:
    account = _account(client, headers)
    response = client.post(
        f"{URL}/payments",
        json={
            "paid_on": (date.today() + timedelta(days=3)).isoformat(),
            "fiscal_year": 2025,
            "component": "inps",
            "kind": "balance",
            "amount": "100.00",
            "account_id": account["id"],
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_a_scheduled_payment_needs_an_account_and_moves_nothing(
    client: TestClient, headers: dict
) -> None:
    response = client.post(
        f"{URL}/payments",
        json={
            "status": "scheduled",
            "paid_on": "2026-11-30",
            "fiscal_year": 2026,
            "component": "stamp_duty",
            "kind": "q3",
            "amount": "6.00",
        },
        headers=headers,
    )
    assert response.status_code == 422

    account = _account(client, headers)
    _movement(client, headers, account["id"], "100.00", "2025-01-10", "income")
    before = _net_worth(client, headers)
    payment = _schedule(client, headers, account["id"])
    assert payment["status"] == "scheduled"
    assert payment["transaction_id"] is None
    assert payment["account_id"] == account["id"]
    after = _net_worth(client, headers)
    assert after["total_net_worth"] == before["total_net_worth"]
    assert _balance(client, headers, account["id"]) == Decimal("100.00")


def test_confirming_writes_the_leg_on_the_actual_date(client: TestClient, headers: dict) -> None:
    account = _account(client, headers)
    _movement(client, headers, account["id"], "100.00", "2025-01-10", "income")
    payment = _schedule(client, headers, account["id"])

    response = client.post(
        f"{URL}/payments/{payment['id']}/execute",
        json={"paid_on": date.today().isoformat()},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    paid = response.json()
    assert paid["status"] == "paid"
    assert paid["owns_transaction"] is True
    assert paid["paid_on"] == date.today().isoformat()
    assert _balance(client, headers, account["id"]) == Decimal("94.00")

    # Confirming twice is refused; undoing puts it back as scheduled.
    again = client.post(
        f"{URL}/payments/{payment['id']}/execute",
        json={"paid_on": date.today().isoformat()},
        headers=headers,
    )
    assert again.status_code == 409
    undone = client.post(f"{URL}/payments/{payment['id']}/unexecute", headers=headers)
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "scheduled"
    assert _balance(client, headers, account["id"]) == Decimal("100.00")


def test_confirming_by_linking_the_imported_debit(client: TestClient, headers: dict) -> None:
    account = _account(client, headers)
    _movement(client, headers, account["id"], "100.00", "2025-01-10", "income")
    payment = _schedule(client, headers, account["id"], paid_on=date.today().isoformat())
    debit = _movement(client, headers, account["id"], "-6.00", date.today().isoformat(), "expense")

    candidates = client.get(f"{URL}/payments/{payment['id']}/candidates", headers=headers)
    assert candidates.status_code == 200, candidates.text
    assert [c["id"] for c in candidates.json()] == [debit["id"]]

    response = client.post(
        f"{URL}/payments/{payment['id']}/execute",
        json={"paid_on": date.today().isoformat(), "transaction_id": debit["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["owns_transaction"] is False
    movement = client.get(f"/api/v1/transactions/{debit['id']}", headers=headers).json()
    # Cash basis: still a spend, filed under taxes.
    assert movement["type"] == "expense"
    categories = client.get("/api/v1/categories", headers=headers).json()
    taxes = next(c for c in categories if c["id"] == movement["category_id"])
    assert (taxes["name"], taxes["type"]) == ("Tasse", "expense")
    # Cash moved once, not twice.
    assert _balance(client, headers, account["id"]) == Decimal("94.00")
    # The bank's record can't be deleted from under the F24.
    assert client.delete(f"/api/v1/transactions/{debit['id']}", headers=headers).status_code == 409

    # Unlinked, it stays where it is: it happened, and it is still an expense.
    deleted = client.delete(f"{URL}/payments/{payment['id']}", headers=headers)
    assert deleted.status_code == 204
    movement = client.get(f"/api/v1/transactions/{debit['id']}", headers=headers).json()
    assert movement["type"] == "expense"
    assert movement["category_id"] is not None
    assert _balance(client, headers, account["id"]) == Decimal("94.00")


def test_linking_a_movement_of_another_amount_is_refused(client: TestClient, headers: dict) -> None:
    account = _account(client, headers)
    payment = _schedule(client, headers, account["id"])
    debit = _movement(client, headers, account["id"], "-7.00", date.today().isoformat(), "expense")
    response = client.post(
        f"{URL}/payments/{payment['id']}/execute",
        json={"paid_on": date.today().isoformat(), "transaction_id": debit["id"]},
        headers=headers,
    )
    assert response.status_code == 422


def test_an_account_a_debit_is_due_from_cannot_be_deleted(
    client: TestClient, headers: dict
) -> None:
    account = _account(client, headers)
    _schedule(client, headers, account["id"])
    response = client.delete(f"/api/v1/accounts/{account['id']}", headers=headers)
    assert response.status_code == 409


def test_summary_deadlines_show_what_is_scheduled(client: TestClient, headers: dict) -> None:
    account = _account(client, headers)
    response = client.post(
        f"{URL}/invoices",
        json={"client": "Acme", "issue_date": "2025-08-01", "amount": "500.00"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    _schedule(client, headers, account["id"], amount="2.00")

    summary = client.get(f"{URL}/summary?year=2025", headers=headers).json()
    q3 = next(d for d in summary["deadlines"] if d["component"] == "stamp_duty")
    assert q3["kind"] == "q3"
    assert q3["due_date"] == "2025-12-01"  # 30 November 2025 is a Sunday
    assert Decimal(q3["amount_due"]) == Decimal("2.00")
    assert Decimal(q3["amount_scheduled"]) == Decimal("2.00")
    assert Decimal(summary["figures"]["stamp_duty"]) == Decimal("2.00")


# ---------------------------------------------------------------------------
# Vehicle deadlines
# ---------------------------------------------------------------------------


def _vehicle(client: TestClient, headers: dict) -> dict:
    response = client.post(
        "/api/v1/physical-assets",
        json={
            "kind": "vehicle",
            "name": "Panda",
            "currency": "EUR",
            "purchase_date": "2024-01-10",
            "purchase_price": "12000.00",
            "vehicle_type": "car",
            "depreciation_rate": "0.15",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _deadline(client: TestClient, headers: dict, vehicle_id: str, **overrides) -> dict:
    payload = {
        "physical_asset_id": vehicle_id,
        "kind": "insurance",
        "due_date": (date.today() + timedelta(days=10)).isoformat(),
        **overrides,
    }
    response = client.post("/api/v1/vehicle-deadlines", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_completing_a_deadline_can_create_the_next_one(client: TestClient, headers: dict) -> None:
    vehicle = _vehicle(client, headers)
    deadline = _deadline(client, headers, vehicle["id"], amount="420.00")
    next_year = (date.fromisoformat(deadline["due_date"]) + timedelta(days=365)).isoformat()

    response = client.post(
        f"/api/v1/vehicle-deadlines/{deadline['id']}/complete",
        json={"done_on": date.today().isoformat(), "next_due_date": next_year},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    done, following = response.json()
    assert done["done_on"] == date.today().isoformat()
    assert following["due_date"] == next_year
    assert following["amount"] == "420.00"

    open_ = client.get("/api/v1/vehicle-deadlines", headers=headers).json()
    assert [d["id"] for d in open_] == [following["id"]]
    every = client.get("/api/v1/vehicle-deadlines?include_done=true", headers=headers).json()
    assert len(every) == 2


def test_an_other_deadline_needs_a_name_and_an_account_needs_an_amount(
    client: TestClient, headers: dict
) -> None:
    vehicle = _vehicle(client, headers)
    account = _account(client, headers)
    base = {"physical_asset_id": vehicle["id"], "due_date": "2026-12-01"}
    assert (
        client.post("/api/v1/vehicle-deadlines", json={**base, "kind": "other"}, headers=headers)
    ).status_code == 422
    assert (
        client.post(
            "/api/v1/vehicle-deadlines",
            json={**base, "kind": "service", "account_id": account["id"]},
            headers=headers,
        )
    ).status_code == 422


def test_deleting_the_vehicle_drops_its_deadlines(client: TestClient, headers: dict) -> None:
    vehicle = _vehicle(client, headers)
    _deadline(client, headers, vehicle["id"])
    assert (
        client.delete(f"/api/v1/physical-assets/{vehicle['id']}", headers=headers).status_code
        == 204
    )
    assert client.get("/api/v1/vehicle-deadlines", headers=headers).json() == []


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def _alerts(client: TestClient, headers: dict) -> dict:
    response = client.get("/api/v1/alerts", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_margin_is_the_larger_of_fifteen_and_a_fifth() -> None:
    assert alerts_service.margin_for(Decimal("6")) == Decimal("15")
    assert alerts_service.margin_for(Decimal("1000")) == Decimal("200.00")


def test_an_account_that_cannot_cover_its_debits_alerts_on_every_visit(
    client: TestClient, headers: dict
) -> None:
    account = _account(client, headers)
    _movement(client, headers, account["id"], "4.00", "2025-01-10", "income")
    _schedule(client, headers, account["id"])

    body = _alerts(client, headers)
    short = next(a for a in body["alerts"] if a["kind"] == "account_short")
    assert short["tone"] == "danger"
    assert short["repeat"] == "every_visit"
    assert Decimal(short["balance"]) == Decimal("4.00")
    assert Decimal(short["committed"]) == Decimal("6.00")
    commitment = body["commitments"][0]
    assert Decimal(commitment["threshold"]) == Decimal("21.00")
    assert commitment["last_movement_on"] == "2025-01-10"


def test_an_account_close_to_its_debits_warns_once(client: TestClient, headers: dict) -> None:
    account = _account(client, headers)
    _movement(client, headers, account["id"], "15.00", "2025-01-10", "income")
    _schedule(client, headers, account["id"])

    near = next(a for a in _alerts(client, headers)["alerts"] if a["kind"] == "account_near")
    assert near["repeat"] == "once"
    assert near["id"].endswith(":6.00")


def test_a_well_covered_account_raises_nothing(client: TestClient, headers: dict) -> None:
    account = _account(client, headers)
    _movement(client, headers, account["id"], "500.00", "2025-01-10", "income")
    _schedule(client, headers, account["id"])
    kinds = {a["kind"] for a in _alerts(client, headers)["alerts"]}
    assert not kinds & {"account_short", "account_near"}


def test_a_scheduled_debit_past_its_date_asks_to_be_confirmed(
    client: TestClient, headers: dict
) -> None:
    account = _account(client, headers)
    _movement(client, headers, account["id"], "500.00", "2025-01-10", "income")
    _schedule(
        client, headers, account["id"], paid_on=(date.today() - timedelta(days=2)).isoformat()
    )
    kinds = {a["kind"] for a in _alerts(client, headers)["alerts"]}
    assert "scheduled_unconfirmed" in kinds


def test_vehicle_deadlines_alert_within_two_weeks_and_commit_the_account(
    client: TestClient, headers: dict
) -> None:
    vehicle = _vehicle(client, headers)
    account = _account(client, headers)
    _movement(client, headers, account["id"], "1000.00", "2025-01-10", "income")
    _deadline(client, headers, vehicle["id"], amount="420.00", account_id=account["id"])
    _deadline(
        client,
        headers,
        vehicle["id"],
        kind="inspection",
        due_date=(date.today() + timedelta(days=60)).isoformat(),
    )

    body = _alerts(client, headers)
    vehicle_alerts = [a for a in body["alerts"] if a["kind"].startswith("vehicle_")]
    assert [a["label"] for a in vehicle_alerts] == ["Panda · assicurazione"]
    assert Decimal(body["commitments"][0]["committed"]) == Decimal("420.00")


def test_f24_lines_neither_paid_nor_scheduled_alert(
    client: TestClient, headers: dict, db_session: Session
) -> None:
    response = client.post(
        f"{URL}/invoices",
        json={"client": "Acme", "issue_date": "2026-08-01", "amount": "500.00"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    user = db_session.query(User).filter(User.email == "test.user@example.com").one()

    upcoming = alerts_service.build_alerts(db_session, user, today=date(2026, 11, 25))
    f24 = [a for a in upcoming.alerts if a.kind.startswith("f24_")]
    assert [(a.kind, a.due_date, a.amount) for a in f24] == [
        ("f24_upcoming", date(2026, 11, 30), Decimal("2.00"))
    ]
    overdue = alerts_service.build_alerts(db_session, user, today=date(2026, 12, 2))
    assert [a.kind for a in overdue.alerts if a.kind.startswith("f24_")] == ["f24_overdue"]
    # A month earlier it isn't news yet.
    assert not [
        a
        for a in alerts_service.build_alerts(db_session, user, today=date(2026, 10, 1)).alerts
        if a.kind.startswith("f24_")
    ]


# ---------------------------------------------------------------------------
# Changing the account
# ---------------------------------------------------------------------------

def _pay(client: TestClient, headers: dict, account_id: str, **overrides) -> dict:
    payload = {
        "paid_on": "2025-12-01",
        "fiscal_year": 2025,
        "component": "stamp_duty",
        "kind": "q3",
        "amount": "6.00",
        "account_id": account_id,
        **overrides,
    }
    response = client.post(f"{URL}/payments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_moving_a_paid_f24_to_another_account_moves_its_leg(
    client: TestClient, headers: dict
) -> None:
    first, second = _account(client, headers, "Primo"), _account(client, headers, "Secondo")
    payment = _pay(client, headers, first["id"])
    before = _net_worth(client, headers)["total_net_worth"]

    response = client.patch(
        f"{URL}/payments/{payment['id']}", json={"account_id": second["id"]}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["account_id"] == second["id"]
    assert response.json()["transaction_id"] == payment["transaction_id"]
    assert _balance(client, headers, first["id"]) == Decimal("0")
    assert _balance(client, headers, second["id"]) == Decimal("-6.00")
    assert _net_worth(client, headers)["total_net_worth"] == before


def test_a_paid_f24_recorded_without_an_account_gets_its_leg(
    client: TestClient, headers: dict, db_session: Session
) -> None:
    from app.models import TaxPayment

    user = db_session.query(User).filter(User.email == "test.user@example.com").one()
    legacy = TaxPayment(
        user_id=user.id,
        paid_on=date(2025, 12, 1),
        fiscal_year=2025,
        component="stamp_duty",
        kind="q3",
        amount=Decimal("6.00"),
    )
    db_session.add(legacy)
    db_session.flush()
    account = _account(client, headers)

    response = client.patch(
        f"{URL}/payments/{legacy.id}", json={"account_id": account["id"]}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["transaction_id"] is not None
    assert _balance(client, headers, account["id"]) == Decimal("-6.00")


def test_a_linked_f24_keeps_the_banks_account(client: TestClient, headers: dict) -> None:
    first, second = _account(client, headers, "Primo"), _account(client, headers, "Secondo")
    payment = _schedule(client, headers, first["id"], paid_on=date.today().isoformat())
    debit = _movement(client, headers, first["id"], "-6.00", date.today().isoformat(), "expense")
    response = client.post(
        f"{URL}/payments/{payment['id']}/execute",
        json={"paid_on": date.today().isoformat(), "transaction_id": debit["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = client.patch(
        f"{URL}/payments/{payment['id']}", json={"account_id": second["id"]}, headers=headers
    )
    assert response.status_code == 409


def test_a_scheduled_debit_can_move_to_another_account(client: TestClient, headers: dict) -> None:
    first, second = _account(client, headers, "Primo"), _account(client, headers, "Secondo")
    payment = _schedule(client, headers, first["id"])
    response = client.patch(
        f"{URL}/payments/{payment['id']}", json={"account_id": second["id"]}, headers=headers
    )
    assert response.status_code == 200, response.text
    commitments = _alerts(client, headers)["commitments"]
    assert [c["account_id"] for c in commitments] == [second["id"]]


def test_an_overdue_line_from_last_year_shows_with_this_years_deadlines(
    client: TestClient, headers: dict
) -> None:
    """The banner flags it; the page must list it, or there's nowhere to record it."""
    year = date.today().year
    last = year - 1
    response = client.post(
        f"{URL}/invoices",
        json={"client": "Acme", "issue_date": f"{last}-08-01", "amount": "500.00"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    due = service.stamp_duty_due_date(last, 3, {})
    rows = client.get(f"{URL}/summary?year={year}", headers=headers).json()["deadlines"]
    overdue = [d for d in rows if d["component"] == "stamp_duty" and d["fiscal_year"] == last]
    assert [(d["kind"], d["due_date"]) for d in overdue] == [("q3", due.isoformat())]

    account = _account(client, headers)
    _pay(client, headers, account["id"], amount="2.00", fiscal_year=last, paid_on=due.isoformat())
    rows = client.get(f"{URL}/summary?year={year}", headers=headers).json()["deadlines"]
    assert not [d for d in rows if d["fiscal_year"] == last and d["component"] == "stamp_duty"]
