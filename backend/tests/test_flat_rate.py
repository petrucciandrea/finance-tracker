"""
Tests for the P.IVA forfettaria section: the per-invoice arithmetic, the
year figures (cash basis, INPS deduction, advances), the suggested
provision rate, the liability net worth subtracts, and the movements on
accounts the invoices and F24 payments own.

The pure computations are tested on a hand-built `Ledger`; everything that
touches rows goes through the API. Dates are in the past on purpose: the
summary and net worth read "today".
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services import flat_rate as service

URL = "/api/v1/flat-rate"

# The user's own numbers: ATECO 78%, 5% start-up rate, gestione separata.
PARAMS = {
    "profitability_coefficient": "0.78",
    "substitute_tax_rate": "0.05",
    "inps_rate": "0.2623",
    "rivalsa_rate": "0.04",
}
YEAR_ROW = service.YearRow(
    profitability_coefficient=Decimal("0.78"),
    substitute_tax_rate=Decimal("0.05"),
    inps_rate=Decimal("0.2623"),
    rivalsa_rate=Decimal("0.04"),
)


@pytest.fixture(autouse=True)
def _mock_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_from_yahoo_finance", lambda symbol: Decimal("150.00")
    )
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_currency_from_yahoo_finance", lambda symbol: "EUR"
    )


@pytest.fixture
def headers(client: TestClient, registered_user: dict) -> dict:
    headers = registered_user["auth_headers"]
    for year in (2024, 2025, 2026):
        response = client.patch(f"{URL}/years/{year}", json=PARAMS, headers=headers)
        assert response.status_code == 200, response.text
    return headers


@pytest.fixture
def account(client: TestClient, headers: dict) -> dict:
    return _account(client, headers, "Conto")


def _account(
    client: TestClient,
    headers: dict,
    name: str,
    currency: str = "EUR",
    account_type: str = "checking",
) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "type": account_type, "currency": currency},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _invoice(api: TestClient, headers: dict, **overrides) -> dict:
    # `api`, not `client`: an invoice has a `client` field to override.
    payload = {"client": "Acme", "issue_date": "2025-03-01", "amount": "1000.00", **overrides}
    response = api.post(f"{URL}/invoices", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _collect(client: TestClient, headers: dict, invoice_id: str, **payload):
    return client.post(f"{URL}/invoices/{invoice_id}/collect", json=payload, headers=headers)


def _net_worth(client: TestClient, headers: dict) -> dict:
    response = client.get("/api/v1/portfolio/net-worth", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _balance(client: TestClient, headers: dict, account_id: str) -> Decimal:
    accounts = _net_worth(client, headers)["accounts"]
    return Decimal(next(a["balance"] for a in accounts if a["account_id"] == account_id))


def _ledger(invoices=(), payments=(), activity_start=None) -> service.Ledger:
    return service.Ledger(
        invoices=list(invoices),
        payments=list(payments),
        params={y: YEAR_ROW for y in range(2024, 2030)},
        activity_start=activity_start,
        safety_margin=Decimal("0.15"),
    )


def _collected(amount: str, on: date) -> SimpleNamespace:
    """A collected invoice with no rivalsa or bollo: its total is `amount`."""
    return SimpleNamespace(
        amount=Decimal(amount),
        rivalsa_rate=Decimal("0"),
        stamp_duty=False,
        collected_on=on,
        issue_date=on,
        provision_rate=None,
    )


def _paid(amount: str, on: date, fiscal_year: int, component: str, kind: str):
    return SimpleNamespace(
        amount=Decimal(amount),
        paid_on=on,
        fiscal_year=fiscal_year,
        component=component,
        kind=kind,
    )


# ---------------------------------------------------------------------------
# One invoice
# ---------------------------------------------------------------------------

def test_invoice_breakdown_matches_the_spreadsheet(client: TestClient, headers: dict) -> None:
    invoice = _invoice(client, headers)

    assert Decimal(invoice["rivalsa_amount"]) == Decimal("40.00")
    assert invoice["stamp_duty"] is True
    assert Decimal(invoice["total"]) == Decimal("1042.00")
    assert Decimal(invoice["taxable_base"]) == Decimal("812.76")
    assert Decimal(invoice["substitute_tax"]) == Decimal("40.64")
    assert Decimal(invoice["inps"]) == Decimal("213.19")
    assert Decimal(invoice["substitute_tax_advance"]) == Decimal("40.64")
    assert Decimal(invoice["inps_advance"]) == Decimal("170.55")


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("70.00", False), ("74.49", False), ("75.00", True)],  # 74.49 + 2.98 = 77.47
)
def test_stamp_duty_applies_above_the_threshold_including_rivalsa(
    client: TestClient, headers: dict, amount: str, expected: bool
) -> None:
    assert _invoice(client, headers, amount=amount)["stamp_duty"] is expected


def test_clients_are_listed_once_most_recent_first(client: TestClient, headers: dict) -> None:
    _invoice(client, headers, client="Acme", issue_date="2025-01-10")
    _invoice(client, headers, client="Beta", issue_date="2025-02-10")
    _invoice(client, headers, client="Acme", issue_date="2025-03-10")
    deleted = _invoice(client, headers, client="Gamma", issue_date="2025-04-10")
    client.delete(f"{URL}/invoices/{deleted['id']}", headers=headers)

    assert client.get(f"{URL}/clients", headers=headers).json() == ["Acme", "Beta"]


def test_stamp_duty_and_rivalsa_can_be_overridden(client: TestClient, headers: dict) -> None:
    invoice = _invoice(client, headers, stamp_duty=False, rivalsa_rate="0")
    assert Decimal(invoice["total"]) == Decimal("1000.00")


def test_rivalsa_rate_is_frozen_on_the_invoice(client: TestClient, headers: dict) -> None:
    invoice = _invoice(client, headers)
    client.patch(f"{URL}/years/2025", json={"rivalsa_rate": "0"}, headers=headers)

    listed = client.get(f"{URL}/invoices", headers=headers).json()
    assert [Decimal(i["rivalsa_amount"]) for i in listed] == [Decimal("40.00")]
    assert listed[0]["id"] == invoice["id"]


def test_a_new_year_copies_the_previous_one(client: TestClient, headers: dict) -> None:
    client.patch(
        f"{URL}/years/2026", json={"inps_rate": "0.27", "provision_rate": "0.5"}, headers=headers
    )
    year = client.get(f"{URL}/years/2027", headers=headers).json()

    assert Decimal(year["inps_rate"]) == Decimal("0.27")
    # The per-year choices aren't copied: the provision restarts on the
    # suggestion, the tax rate on automatic.
    assert year["provision_rate"] is None
    assert year["substitute_tax_rate_is_automatic"] is True


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2025, "0.15"), (2026, "0.05"), (2030, "0.05"), (2031, "0.15")],
)
def test_the_tax_rate_is_five_percent_for_the_first_five_years(
    client: TestClient, registered_user: dict, year: int, expected: str
) -> None:
    headers = registered_user["auth_headers"]
    client.patch(f"{URL}/settings", json={"activity_start_date": "2026-06-01"}, headers=headers)

    params = client.get(f"{URL}/years/{year}", headers=headers).json()
    assert params["substitute_tax_rate_is_automatic"] is True
    assert Decimal(params["substitute_tax_rate"]) == Decimal(expected)
    assert params["startup_last_year"] == 2030


def test_the_automatic_rate_follows_the_start_date(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]

    def rate() -> Decimal:
        response = client.get(f"{URL}/years/2026", headers=headers)
        return Decimal(response.json()["substitute_tax_rate"])

    # No start date yet: the safe side.
    assert rate() == Decimal("0.15")
    client.patch(f"{URL}/settings", json={"activity_start_date": "2026-06-01"}, headers=headers)
    assert rate() == Decimal("0.05")


def test_an_explicit_tax_rate_overrides_and_null_restores_automatic(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    client.patch(f"{URL}/settings", json={"activity_start_date": "2026-06-01"}, headers=headers)

    forced = client.patch(
        f"{URL}/years/2026", json={"substitute_tax_rate": "0.15"}, headers=headers
    ).json()
    assert forced["substitute_tax_rate_is_automatic"] is False
    assert Decimal(forced["substitute_tax_rate"]) == Decimal("0.15")

    restored = client.patch(
        f"{URL}/years/2026", json={"substitute_tax_rate": None}, headers=headers
    ).json()
    assert restored["substitute_tax_rate_is_automatic"] is True
    assert Decimal(restored["substitute_tax_rate"]) == Decimal("0.05")


# ---------------------------------------------------------------------------
# Year figures
# ---------------------------------------------------------------------------

def test_taxes_follow_the_collection_date_not_the_issue_date(
    client: TestClient, headers: dict
) -> None:
    invoice = _invoice(client, headers, issue_date="2024-12-15")
    assert _collect(client, headers, invoice["id"], collected_on="2025-01-10").status_code == 200

    issued_year = client.get(f"{URL}/summary?year=2024", headers=headers).json()
    collected_year = client.get(f"{URL}/summary?year=2025", headers=headers).json()

    assert Decimal(issued_year["figures"]["revenue"]) == Decimal("0")
    assert Decimal(collected_year["figures"]["revenue"]) == Decimal("1042.00")
    # Listed under both years: issued in one, taxed in the other.
    for year in (2024, 2025):
        listed = client.get(f"{URL}/invoices?year={year}", headers=headers).json()
        assert [i["id"] for i in listed] == [invoice["id"]]
    assert client.get(f"{URL}/invoices?year=2025", headers=headers).json()[0]["fiscal_year"] == 2025


def test_inps_paid_in_the_year_is_deducted_from_the_tax_base() -> None:
    sales = [_collected("10000", date(2025, 3, 1))]
    without = service.year_figures(_ledger(sales), 2025)
    with_payment = service.year_figures(
        _ledger(sales, [_paid("1000", date(2025, 6, 30), 2024, "inps", "balance")]), 2025
    )

    assert without.substitute_tax == Decimal("390.00")  # 10000 × 78% × 5%
    assert with_payment.inps_deducted == Decimal("1000.00")
    assert with_payment.substitute_tax == Decimal("340.00")  # (7800 − 1000) × 5%
    # The contributions themselves are computed on the undeducted base.
    assert with_payment.inps == without.inps == Decimal("2045.94")


@pytest.mark.parametrize(
    ("tax", "first", "second"),
    [
        ("51.65", "0", "0"),  # at or below €51.65: no advance
        ("200.00", "0", "200.00"),  # below €257.52: one November payment
        ("1000.00", "400.00", "600.00"),  # 40% June, 60% November
    ],
)
def test_tax_advance_thresholds(tax: str, first: str, second: str) -> None:
    figures = service.YearFigures(
        year=2025,
        revenue=Decimal("0"),
        taxable_base=Decimal("0"),
        inps=Decimal("1000.00"),
        inps_deducted=Decimal("0"),
        substitute_tax=Decimal(tax),
    )
    advances = service.advances_from(figures)
    assert (advances.tax_first, advances.tax_second) == (Decimal(first), Decimal(second))
    assert (advances.inps_first, advances.inps_second) == (Decimal("400.00"), Decimal("400.00"))


def test_first_year_cash_requirement_includes_next_years_advances() -> None:
    ledger = _ledger([_collected("10000", date(2025, 3, 1))])
    figures = service.year_figures(ledger, 2025)
    requirement = service.cash_requirement(ledger, date(2025, 12, 31))

    assert requirement == figures.liability + service.advances_from(figures).total
    # The liability net worth sees is only the year's own taxes.
    assert service.tax_liability(ledger, date(2025, 12, 31)) == figures.liability


def test_advances_paid_ahead_of_the_income_read_as_a_credit() -> None:
    ledger = _ledger(
        [_collected("10000", date(2025, 3, 1))],
        [
            _paid("2435.94", date(2026, 6, 30), 2025, "inps", "balance"),
            _paid("1636.75", date(2026, 6, 30), 2026, "inps", "first_advance"),
        ],
    )
    # 2025's INPS settled, plus an advance on 2026 income not yet earned:
    # only 2025's tax is owed, minus the advance.
    figures = service.year_figures(ledger, 2025)
    liability = service.tax_liability(ledger, date(2026, 7, 1))
    assert liability == figures.liability - Decimal("2435.94") - Decimal("1636.75")


def test_deadlines_split_balance_and_advances() -> None:
    ledger = _ledger([_collected("10000", date(2025, 3, 1))])
    rows = service.deadlines(ledger, 2026, date(2026, 1, 15))
    by_key = {(r.due_date, r.fiscal_year, r.component, r.kind): r.amount_due for r in rows}

    june, november = date(2026, 6, 30), date(2026, 11, 30)
    assert by_key[(june, 2025, "substitute_tax", "balance")] == Decimal("390.00")
    assert by_key[(june, 2025, "inps", "balance")] == Decimal("2045.94")
    assert by_key[(june, 2026, "substitute_tax", "first_advance")] == Decimal("156.00")
    assert by_key[(november, 2026, "substitute_tax", "second_advance")] == Decimal("234.00")
    assert by_key[(june, 2026, "inps", "first_advance")] == Decimal("818.38")
    assert by_key[(november, 2026, "inps", "second_advance")] == Decimal("818.37")
    assert not any(r.is_estimate for r in rows if r.due_date.year == 2026)


# ---------------------------------------------------------------------------
# Suggested provision rate
# ---------------------------------------------------------------------------

def test_suggested_rate_follows_the_spreadsheets_progression() -> None:
    """Start in June 2026, then a full 2027: 55% → 40% → 30%."""
    sales = [_collected("1000", date(2026, month, 15)) for month in range(6, 13)]
    sales += [_collected("1000", date(2027, month, 15)) for month in range(1, 13)]
    ledger = _ledger(sales, activity_start=date(2026, 6, 1))

    assert service.suggest_provision_rate(ledger, 2026).suggested_rate == Decimal("0.55")
    assert service.suggest_provision_rate(ledger, 2027).suggested_rate == Decimal("0.40")
    assert service.suggest_provision_rate(ledger, 2028).suggested_rate == Decimal("0.30")


def test_an_explicit_rate_wins_over_the_suggestion(client: TestClient, headers: dict) -> None:
    year = client.patch(
        f"{URL}/years/2025", json={"provision_rate": "0.35"}, headers=headers
    ).json()
    assert Decimal(year["effective_provision_rate"]) == Decimal("0.35")

    invoice = _invoice(client, headers)
    assert Decimal(invoice["to_provision"]) == Decimal("364.70")  # 1042 × 35%
    override = _invoice(client, headers, provision_rate="0.5")
    assert Decimal(override["to_provision"]) == Decimal("521.00")

    cleared = client.patch(f"{URL}/years/2025", json={"provision_rate": None}, headers=headers)
    assert cleared.json()["provision_rate"] is None


# ---------------------------------------------------------------------------
# Net worth
# ---------------------------------------------------------------------------

def test_collecting_lowers_net_worth_by_the_tax_share_only(
    client: TestClient, headers: dict, account: dict
) -> None:
    invoice = _invoice(client, headers)
    _collect(client, headers, invoice["id"], collected_on="2025-03-15", account_id=account["id"])

    net_worth = _net_worth(client, headers)
    liability = Decimal("40.64") + Decimal("213.19")
    assert Decimal(net_worth["total_cash_balance"]) == Decimal("1042.00")
    assert Decimal(net_worth["total_tax_liability"]) == liability
    assert Decimal(net_worth["total_net_worth"]) == Decimal("1042.00") - liability


def test_paying_an_f24_leaves_net_worth_unchanged(
    client: TestClient, headers: dict, account: dict
) -> None:
    invoice = _invoice(client, headers)
    _collect(client, headers, invoice["id"], collected_on="2025-03-15", account_id=account["id"])
    before = Decimal(_net_worth(client, headers)["total_net_worth"])

    response = client.post(
        f"{URL}/payments",
        json={
            "paid_on": "2026-06-30",
            "fiscal_year": 2025,
            "component": "substitute_tax",
            "kind": "balance",
            "amount": "40.64",
            "account_id": account["id"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text

    after = _net_worth(client, headers)
    assert Decimal(after["total_net_worth"]) == before
    assert Decimal(after["total_tax_liability"]) == Decimal("213.19")
    assert _balance(client, headers, account["id"]) == Decimal("1001.36")


def test_history_subtracts_the_liability(
    client: TestClient, headers: dict, account: dict
) -> None:
    _income(client, headers, account["id"], "100.00", "2025-01-10")
    invoice = _invoice(client, headers)
    _collect(client, headers, invoice["id"], collected_on="2025-03-15", account_id=account["id"])

    points = client.get("/api/v1/portfolio/history?period=all", headers=headers).json()["points"]
    last = points[-1]
    assert Decimal(last["total_liabilities_base_currency"]) == Decimal("253.83")
    assert Decimal(last["total_net_worth"]) == Decimal("1142.00") - Decimal("253.83")
    # Before the collection there was nothing to owe.
    assert Decimal(points[0]["total_liabilities_base_currency"]) == Decimal("0")


# ---------------------------------------------------------------------------
# Collecting
# ---------------------------------------------------------------------------

def _income(client: TestClient, headers: dict, account_id: str, amount: str, on: str) -> dict:
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "amount": amount,
            "currency": "EUR",
            "date": on,
            "type": "income",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_linking_an_imported_income(client: TestClient, headers: dict, account: dict) -> None:
    invoice = _invoice(client, headers)
    income = _income(client, headers, account["id"], "1042.00", "2025-04-02")
    _income(client, headers, account["id"], "500.00", "2025-04-02")  # wrong amount

    candidates = client.get(f"{URL}/invoices/{invoice['id']}/candidates", headers=headers)
    assert [c["id"] for c in candidates.json()] == [income["id"]]

    linked = _collect(
        client, headers, invoice["id"], collected_on="2025-04-02", transaction_id=income["id"]
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["owns_transaction"] is False

    # One movement settles one invoice.
    other = _invoice(client, headers, client="Beta")
    again = _collect(
        client, headers, other["id"], collected_on="2025-04-02", transaction_id=income["id"]
    )
    assert again.status_code == 409

    # It can't be deleted from under the invoice, but undoing the collection
    # leaves the bank's movement alone.
    assert client.delete(f"/api/v1/transactions/{income['id']}", headers=headers).status_code == 409
    client.post(f"{URL}/invoices/{invoice['id']}/uncollect", headers=headers)
    assert _balance(client, headers, account["id"]) == Decimal("1542.00")


def test_collecting_onto_an_account_writes_an_income(
    client: TestClient, headers: dict, account: dict
) -> None:
    invoice = _invoice(client, headers)
    collected = _collect(
        client, headers, invoice["id"], collected_on="2025-03-15", account_id=account["id"]
    ).json()
    assert collected["owns_transaction"] is True
    assert collected["transaction_account_id"] == account["id"]

    transaction = client.get(
        f"/api/v1/transactions/{collected['transaction_id']}", headers=headers
    ).json()
    assert transaction["type"] == "income"
    assert transaction["category_id"] is not None  # "Varie", like any income

    # Its amount belongs to the invoice: editing it there is refused...
    refused = client.patch(
        f"/api/v1/transactions/{transaction['id']}", json={"amount": "1.00"}, headers=headers
    )
    assert refused.status_code == 409
    # ...and editing the invoice moves it.
    client.patch(f"{URL}/invoices/{invoice['id']}", json={"amount": "2000.00"}, headers=headers)
    assert _balance(client, headers, account["id"]) == Decimal("2082.00")

    client.post(f"{URL}/invoices/{invoice['id']}/uncollect", headers=headers)
    assert _balance(client, headers, account["id"]) == Decimal("0")


def test_redating_a_collection_moves_its_income_and_its_year(
    client: TestClient, headers: dict, account: dict
) -> None:
    invoice = _invoice(client, headers, issue_date="2024-12-15")
    collected = _collect(
        client, headers, invoice["id"], collected_on="2024-12-28", account_id=account["id"]
    ).json()

    response = client.patch(
        f"{URL}/invoices/{invoice['id']}", json={"collected_on": "2025-01-05"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["fiscal_year"] == 2025

    income = client.get(f"/api/v1/transactions/{collected['transaction_id']}", headers=headers)
    assert income.json()["date"] == "2025-01-05"
    revenue = client.get(f"{URL}/summary?year=2025", headers=headers).json()["figures"]["revenue"]
    assert Decimal(revenue) == Decimal("1042.00")


def test_redating_a_linked_collection_leaves_the_bank_movement(
    client: TestClient, headers: dict, account: dict
) -> None:
    invoice = _invoice(client, headers)
    income = _income(client, headers, account["id"], "1042.00", "2025-04-02")
    _collect(client, headers, invoice["id"], collected_on="2025-04-02", transaction_id=income["id"])

    client.patch(
        f"{URL}/invoices/{invoice['id']}", json={"collected_on": "2025-04-01"}, headers=headers
    )
    moved = client.get(f"/api/v1/transactions/{income['id']}", headers=headers).json()
    assert moved["date"] == "2025-04-02"


def test_a_collection_date_cant_be_set_cleared_or_moved_past_a_close(
    client: TestClient, headers: dict, account: dict
) -> None:
    invoice = _invoice(client, headers)
    url = f"{URL}/invoices/{invoice['id']}"
    # Not collected yet: that's /collect.
    early = client.patch(url, json={"collected_on": "2025-04-01"}, headers=headers)
    assert early.status_code == 409

    _collect(client, headers, invoice["id"], collected_on="2025-03-15", account_id=account["id"])
    assert client.patch(url, json={"collected_on": None}, headers=headers).status_code == 422

    client.patch(
        f"/api/v1/accounts/{account['id']}", json={"closed_at": "2025-03-31"}, headers=headers
    )
    after_close = client.patch(url, json={"collected_on": "2025-04-10"}, headers=headers)
    assert after_close.status_code == 409


def test_collecting_onto_a_closed_or_foreign_account_is_refused(
    client: TestClient, headers: dict, account: dict
) -> None:
    invoice = _invoice(client, headers)
    client.patch(
        f"/api/v1/accounts/{account['id']}", json={"closed_at": "2025-01-31"}, headers=headers
    )
    closed = _collect(
        client, headers, invoice["id"], collected_on="2025-03-15", account_id=account["id"]
    )
    assert closed.status_code == 409

    dollars = _account(client, headers, "USD", currency="USD")
    foreign = _collect(
        client, headers, invoice["id"], collected_on="2025-03-15", account_id=dollars["id"]
    )
    assert foreign.status_code == 422


def test_deleting_a_collected_invoice_retires_its_income(
    client: TestClient, headers: dict, account: dict
) -> None:
    invoice = _invoice(client, headers)
    _collect(client, headers, invoice["id"], collected_on="2025-03-15", account_id=account["id"])

    assert client.delete(f"{URL}/invoices/{invoice['id']}", headers=headers).status_code == 204
    assert _balance(client, headers, account["id"]) == Decimal("0")
    assert Decimal(_net_worth(client, headers)["total_tax_liability"]) == Decimal("0")


# ---------------------------------------------------------------------------
# F24 payments
# ---------------------------------------------------------------------------

def test_a_payments_leg_belongs_to_the_payment(
    client: TestClient, headers: dict, account: dict
) -> None:
    payment = client.post(
        f"{URL}/payments",
        json={
            "paid_on": "2026-06-30",
            "fiscal_year": 2025,
            "component": "inps",
            "kind": "balance",
            "amount": "100.00",
            "account_id": account["id"],
        },
        headers=headers,
    ).json()
    assert payment["account_id"] == account["id"]

    leg_url = f"/api/v1/transactions/{payment['transaction_id']}"
    assert client.delete(leg_url, headers=headers).status_code == 409

    client.patch(f"{URL}/payments/{payment['id']}", json={"amount": "150.00"}, headers=headers)
    assert _balance(client, headers, account["id"]) == Decimal("-150.00")

    assert client.delete(f"{URL}/payments/{payment['id']}", headers=headers).status_code == 204
    assert _balance(client, headers, account["id"]) == Decimal("0")


# ---------------------------------------------------------------------------
# Provision sources
# ---------------------------------------------------------------------------

def test_a_provision_account_cant_fund_a_goal_and_vice_versa(
    client: TestClient, headers: dict
) -> None:
    provision = _account(client, headers, "Accantonamento")
    savings = _account(client, headers, "Risparmi")
    goal = client.post(
        "/api/v1/planning/goals",
        json={"name": "Fondo", "kind": "medium_term", "priority": 1, "target_mode": "open_ended"},
        headers=headers,
    ).json()

    added = client.post(f"{URL}/sources", json={"account_id": provision["id"]}, headers=headers)
    assert added.status_code == 201, added.text
    refused = client.post(
        f"/api/v1/planning/goals/{goal['id']}/sources",
        json={"account_id": provision["id"]},
        headers=headers,
    )
    assert refused.status_code == 409

    client.post(
        f"/api/v1/planning/goals/{goal['id']}/sources",
        json={"account_id": savings["id"]},
        headers=headers,
    )
    other_way = client.post(f"{URL}/sources", json={"account_id": savings["id"]}, headers=headers)
    assert other_way.status_code == 409


def test_a_provision_account_cant_be_deleted(client: TestClient, headers: dict) -> None:
    provision = _account(client, headers, "Accantonamento")
    client.post(f"{URL}/sources", json={"account_id": provision["id"]}, headers=headers)
    assert client.delete(f"/api/v1/accounts/{provision['id']}", headers=headers).status_code == 409


def test_provision_cash_is_not_runway(client: TestClient, headers: dict) -> None:
    provision = _account(client, headers, "Accantonamento")
    _income(client, headers, provision["id"], "3000.00", "2025-03-01")
    before = client.get("/api/v1/planning/survival-budget", headers=headers).json()

    client.post(f"{URL}/sources", json={"account_id": provision["id"]}, headers=headers)
    after = client.get("/api/v1/planning/survival-budget", headers=headers).json()

    assert Decimal(before["total_cash_balance"]) - Decimal(after["total_cash_balance"]) == Decimal(
        "3000.00"
    )


def test_a_holding_source_is_valued_with_whole_units_to_buy(
    client: TestClient, headers: dict
) -> None:
    broker = _account(client, headers, "Broker", account_type="investment")
    _income(client, headers, broker["id"], "1000.00", "2025-03-01")
    buy = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": broker["id"],
            "symbol": "XEON.DE",
            "asset_type": "etf",
            "type": "buy",
            "quantity": "4",
            "price": "150.00",
            "date": "2025-03-02",
        },
        headers=headers,
    )
    assert buy.status_code == 201, buy.text
    asset_id = buy.json()["asset"]["id"]

    client.post(f"{URL}/sources", json={"account_id": broker["id"]}, headers=headers)
    status = client.post(
        f"{URL}/sources", json={"account_id": broker["id"], "asset_id": asset_id}, headers=headers
    ).json()

    by_kind = {s["asset"] is None: s for s in status["sources"]}
    assert Decimal(by_kind[True]["value_base_currency"]) == Decimal("400.00")  # 1000 − 600
    assert Decimal(by_kind[False]["value_base_currency"]) == Decimal("600.00")
    assert by_kind[False]["buyable_units"] == 2  # 400 / 150, whole shares only
    assert Decimal(status["total_base_currency"]) == Decimal("1000.00")


def test_a_product_not_held_in_the_account_is_refused(client: TestClient, headers: dict) -> None:
    broker = _account(client, headers, "Broker", account_type="investment")
    other = _account(client, headers, "Altro", account_type="investment")
    _income(client, headers, broker["id"], "1000.00", "2025-03-01")
    buy = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": broker["id"],
            "symbol": "XEON.DE",
            "asset_type": "etf",
            "type": "buy",
            "quantity": "1",
            "price": "150.00",
            "date": "2025-03-02",
        },
        headers=headers,
    ).json()
    refused = client.post(
        f"{URL}/sources",
        json={"account_id": other["id"], "asset_id": buy["asset"]["id"]},
        headers=headers,
    )
    assert refused.status_code == 422


# ---------------------------------------------------------------------------
# Planning: the income base is net of flat-rate taxes
# ---------------------------------------------------------------------------

def _march_with_an_invoice(client: TestClient, headers: dict, account: dict) -> None:
    invoice = _invoice(client, headers)
    _collect(client, headers, invoice["id"], collected_on="2025-03-15", account_id=account["id"])
    expense = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "amount": "-100.00",
            "currency": "EUR",
            "date": "2025-03-20",
            "type": "expense",
        },
        headers=headers,
    )
    assert expense.status_code == 201, expense.text


def test_the_allocation_model_runs_on_income_net_of_taxes(
    client: TestClient, headers: dict, account: dict
) -> None:
    _march_with_an_invoice(client, headers, account)
    status = client.get(
        "/api/v1/planning/allocation-status?date=2025-03-31", headers=headers
    ).json()

    # 1042 collected, of which 40.64 imposta + 213.19 INPS are the State's.
    assert Decimal(status["gross_income_total"]) == Decimal("1042.00")
    assert Decimal(status["flat_rate_tax_total"]) == Decimal("253.83")
    assert Decimal(status["income_total"]) == Decimal("788.17")
    savings = next(b for b in status["buckets"] if b["bucket"] == "savings")
    assert Decimal(savings["actual_amount"]) == Decimal("688.17")  # net − 100 spent


def test_the_waterfall_quota_is_on_net_income(
    client: TestClient, headers: dict, account: dict
) -> None:
    _march_with_an_invoice(client, headers, account)
    plan = client.get("/api/v1/planning/waterfall?date=2025-03-31", headers=headers).json()

    assert Decimal(plan["income_total"]) == Decimal("788.17")
    assert Decimal(plan["flat_rate_tax_total"]) == Decimal("253.83")
    # 10% of 788.17, rounded down so allocations never exceed it (not 104.20 on gross).
    assert Decimal(plan["savings_quota"]) == Decimal("78.81")


def test_a_month_without_invoices_is_untouched(
    client: TestClient, headers: dict, account: dict
) -> None:
    _march_with_an_invoice(client, headers, account)
    status = client.get(
        "/api/v1/planning/allocation-status?date=2025-04-30", headers=headers
    ).json()
    assert Decimal(status["flat_rate_tax_total"]) == Decimal("0")


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_another_users_invoice_is_not_found(client: TestClient, headers: dict) -> None:
    invoice = _invoice(client, headers)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "another-password-1",
            "base_currency": "EUR",
            "accept_terms": True,
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": "another-password-1"},
    ).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}

    assert client.patch(
        f"{URL}/invoices/{invoice['id']}", json={"client": "x"}, headers=other
    ).status_code == 404
    assert client.delete(f"{URL}/invoices/{invoice['id']}", headers=other).status_code == 404
    assert client.get(f"{URL}/invoices", headers=other).json() == []
