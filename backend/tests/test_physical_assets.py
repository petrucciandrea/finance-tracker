"""
Tests for physical assets: vehicles (depreciation + manual re-anchoring),
precious metals (weight × purity × spot), their optional cash legs, sale,
and their place in net worth — counted there, never in cash.

Spot prices and exchange rates are always monkeypatched. The user's base
currency is EUR; USD converts at 0.9, so a metal priced at 100 USD per fine
gram reads as 90 EUR.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services.physical_assets import TROY_OUNCE_GRAMS, vehicle_value

USD_TO_EUR = Decimal("0.9")
# 100 USD per gram of fine metal, expressed per troy ounce as Yahoo quotes it.
SPOT_PER_OUNCE = Decimal("100") * TROY_OUNCE_GRAMS

URL = "/api/v1/physical-assets"


def _fake_rate(db, from_currency: str, to_currency: str, on_date: date) -> Decimal:
    if from_currency == to_currency:
        return Decimal("1")
    assert (from_currency, to_currency) == ("USD", "EUR")
    return USD_TO_EUR


@pytest.fixture(autouse=True)
def _mock_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.asset_prices._fetch_from_yahoo_finance", lambda symbol: SPOT_PER_OUNCE
    )
    # Bound per import site: the router converts the purchase/sale, the
    # service values the asset today, the portfolio router the history.
    for target in (
        "app.routers.physical_assets.get_rate",
        "app.services.physical_assets.get_rate",
        "app.routers.portfolio.get_rate",
    ):
        monkeypatch.setattr(target, _fake_rate)


@pytest.fixture
def checking_account(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Conto", "type": "checking", "currency": "EUR"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _vehicle(**overrides) -> dict:
    return {
        "kind": "vehicle",
        "name": "Panda",
        "currency": "EUR",
        "purchase_date": date.today().isoformat(),
        "purchase_price": "12000.00",
        "vehicle_type": "car",
        "depreciation_rate": "0.15",
        **overrides,
    }


def _metal(**overrides) -> dict:
    return {
        "kind": "metal",
        "name": "Anello 18kt",
        "currency": "EUR",
        "purchase_date": "2025-01-10",
        "metal": "gold",
        "metal_form": "jewelry",
        "weight_grams": "100",
        "purity": "0.75",
        **overrides,
    }


def _create(client: TestClient, headers: dict, payload: dict) -> dict:
    response = client.post(URL, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _cash_balance(client: TestClient, headers: dict, account_id: str) -> Decimal:
    body = client.get("/api/v1/portfolio/net-worth", headers=headers).json()
    return next(
        Decimal(a["balance"]) for a in body["accounts"] if a["account_id"] == account_id
    )


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------

def test_vehicle_depreciates_compounded_per_year() -> None:
    car = SimpleNamespace(
        purchase_date=date(2022, 1, 1),
        purchase_price=Decimal("10000"),
        depreciation_rate=Decimal("0.15"),
        valuations=[],
    )
    # 1461 days = 4 years of 365.25 → 10000 × 0.85⁴
    assert vehicle_value(car, date(2026, 1, 1)) == Decimal("5220.06")  # type: ignore[arg-type]
    assert vehicle_value(car, date(2022, 1, 1)) == Decimal("10000.00")  # type: ignore[arg-type]


def test_a_valuation_re_anchors_the_curve_from_its_date() -> None:
    car = SimpleNamespace(
        purchase_date=date(2022, 1, 1),
        purchase_price=Decimal("10000"),
        depreciation_rate=Decimal("0.15"),
        valuations=[SimpleNamespace(date=date(2024, 1, 1), value=Decimal("9000"))],
    )
    # Before the valuation the purchase is still the anchor...
    assert vehicle_value(car, date(2023, 1, 1)) < Decimal("10000")  # type: ignore[arg-type]
    # ...from it on the valuation is, and the curve keeps sliding after it.
    assert vehicle_value(car, date(2024, 1, 1)) == Decimal("9000.00")  # type: ignore[arg-type]
    # 731 days after the valuation: 9000 × 0.85^(731/365.25), not 10000 × anything.
    assert vehicle_value(car, date(2026, 1, 1)) == Decimal("6501.05")  # type: ignore[arg-type]


def test_metal_is_valued_at_fine_weight_times_spot(
    client: TestClient, registered_user: dict
) -> None:
    body = _create(client, registered_user["auth_headers"], _metal(purchase_price="5000.00"))

    assert Decimal(body["fine_weight_grams"]) == Decimal("75")
    assert Decimal(body["spot_price_per_gram_base_currency"]) == Decimal("90.00")
    # 75 g × 100 USD × 0.9
    assert Decimal(body["current_value_base_currency"]) == Decimal("6750.00")
    assert Decimal(body["pnl_base_currency"]) == Decimal("1750.00")


def test_metal_without_a_cost_has_no_pnl(client: TestClient, registered_user: dict) -> None:
    body = _create(client, registered_user["auth_headers"], _metal())
    assert body["purchase_price"] is None
    assert body["pnl_base_currency"] is None
    assert body["current_value_base_currency"] is not None


def test_an_unavailable_spot_price_leaves_the_value_unknown(
    client: TestClient, registered_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.asset_prices import AssetPriceUnavailable

    def _down(symbol: str) -> Decimal:
        raise AssetPriceUnavailable("down")

    monkeypatch.setattr("app.services.asset_prices._fetch_from_yahoo_finance", _down)
    body = _create(client, registered_user["auth_headers"], _metal())
    assert body["current_value_base_currency"] is None

    net_worth = client.get(
        "/api/v1/portfolio/net-worth", headers=registered_user["auth_headers"]
    ).json()
    assert Decimal(net_worth["total_physical_assets_value"]) == Decimal("0")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        _vehicle(purity="0.75"),  # metal field on a vehicle
        _metal(depreciation_rate="0.1"),  # vehicle field on a metal
        _vehicle(purchase_price=None),  # depreciation needs an anchor
        _metal(weight_grams=None),
        _vehicle(currency="XXX"),
    ],
)
def test_incoherent_fields_are_rejected(
    client: TestClient, registered_user: dict, payload: dict
) -> None:
    response = client.post(URL, json=payload, headers=registered_user["auth_headers"])
    assert response.status_code == 422, response.text


def test_patch_cannot_clear_a_vehicle_price(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    car = _create(client, headers, _vehicle())
    response = client.patch(f"{URL}/{car['id']}", json={"purchase_price": None}, headers=headers)
    assert response.status_code == 422


def test_another_users_asset_is_not_found(
    client: TestClient, registered_user: dict
) -> None:
    car = _create(client, registered_user["auth_headers"], _vehicle())

    client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "another-password-1",
            "base_currency": "EUR",
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": "another-password-1"},
    ).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}

    assert client.patch(f"{URL}/{car['id']}", json={"name": "x"}, headers=other).status_code == 404
    assert client.delete(f"{URL}/{car['id']}", headers=other).status_code == 404
    assert client.get(URL, headers=other).json() == []


# ---------------------------------------------------------------------------
# Cash legs
# ---------------------------------------------------------------------------

def test_paying_from_an_account_writes_a_transfer_leg(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    car = _create(client, headers, _vehicle(account_id=checking_account["id"]))

    assert car["purchase_account_id"] == checking_account["id"]
    assert _cash_balance(client, headers, checking_account["id"]) == Decimal("-12000")

    transactions = client.get("/api/v1/transactions", headers=headers).json()["data"]
    assert [(t["type"], t["description"]) for t in transactions] == [
        ("transfer", "Acquisto Panda")
    ]


def test_paying_account_must_match_the_asset_currency(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    response = client.post(
        URL,
        json=_vehicle(currency="USD", account_id=checking_account["id"]),
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 422


def test_editing_the_price_moves_the_leg(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    car = _create(client, headers, _vehicle(account_id=checking_account["id"]))

    response = client.patch(
        f"{URL}/{car['id']}", json={"purchase_price": "11000.00"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["purchase_price_base_currency"]) == Decimal("11000")
    assert _cash_balance(client, headers, checking_account["id"]) == Decimal("-11000")


# ---------------------------------------------------------------------------
# Sale, valuations, deletion
# ---------------------------------------------------------------------------

def test_sell_and_unsell(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    car = _create(
        client, headers, _vehicle(purchase_date="2024-01-01", account_id=checking_account["id"])
    )

    response = client.post(
        f"{URL}/{car['id']}/sell",
        json={
            "sold_at": date.today().isoformat(),
            "sale_price": "9000.00",
            "account_id": checking_account["id"],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    sold = response.json()
    assert sold["current_value_base_currency"] is None
    assert Decimal(sold["pnl_base_currency"]) == Decimal("-3000.00")
    assert _cash_balance(client, headers, checking_account["id"]) == Decimal("-3000")

    # Sold assets leave the default list and net worth.
    assert client.get(URL, headers=headers).json() == []
    assert len(client.get(f"{URL}?include_sold=true", headers=headers).json()) == 1

    again = client.post(
        f"{URL}/{car['id']}/sell",
        json={"sold_at": date.today().isoformat(), "sale_price": "1.00"},
        headers=headers,
    )
    assert again.status_code == 409

    response = client.post(f"{URL}/{car['id']}/unsell", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["sold_at"] is None
    assert _cash_balance(client, headers, checking_account["id"]) == Decimal("-12000")


def test_valuations_are_vehicle_only_and_one_per_day(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    car = _create(client, headers, _vehicle(purchase_date="2024-01-01"))
    gold = _create(client, headers, _metal())

    valuation = {"date": date.today().isoformat(), "value": "8000.00"}
    response = client.post(f"{URL}/{car['id']}/valuations", json=valuation, headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["current_value_base_currency"]) == Decimal("8000.00")
    assert len(body["valuations"]) == 1

    duplicate = client.post(f"{URL}/{car['id']}/valuations", json=valuation, headers=headers)
    assert duplicate.status_code == 409
    on_metal = client.post(f"{URL}/{gold['id']}/valuations", json=valuation, headers=headers)
    assert on_metal.status_code == 422
    too_early = client.post(
        f"{URL}/{car['id']}/valuations",
        json={"date": "2023-12-31", "value": "1.00"},
        headers=headers,
    )
    assert too_early.status_code == 422

    response = client.delete(
        f"{URL}/{car['id']}/valuations/{body['valuations'][0]['id']}", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["valuations"] == []
    assert Decimal(response.json()["current_value_base_currency"]) < Decimal("12000")


def test_delete_retires_the_cash_leg(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    car = _create(client, headers, _vehicle(account_id=checking_account["id"]))

    assert client.delete(f"{URL}/{car['id']}", headers=headers).status_code == 204
    assert client.get(URL, headers=headers).json() == []
    assert _cash_balance(client, headers, checking_account["id"]) == Decimal("0")


# ---------------------------------------------------------------------------
# Net worth
# ---------------------------------------------------------------------------

def test_net_worth_counts_physical_assets_but_not_as_cash(
    client: TestClient, registered_user: dict, checking_account: dict
) -> None:
    headers = registered_user["auth_headers"]
    _create(client, headers, _vehicle(account_id=checking_account["id"]))
    _create(client, headers, _metal())

    body = client.get("/api/v1/portfolio/net-worth", headers=headers).json()
    assert Decimal(body["total_cash_balance"]) == Decimal("-12000")
    assert Decimal(body["total_physical_assets_value"]) == Decimal("18750.00")
    assert Decimal(body["total_net_worth"]) == Decimal("6750.00")
    assert len(body["physical_assets"]) == 2

    survival = client.get("/api/v1/planning/survival-budget", headers=headers).json()
    assert Decimal(survival["total_cash_balance"]) == Decimal("-12000")


def test_history_includes_physical_assets_from_their_purchase(
    client: TestClient, registered_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.routers.portfolio.get_rate_history",
        lambda db, from_currency, to_currency, start_date, end_date: {},
    )
    monkeypatch.setattr(
        "app.routers.portfolio.asset_prices_service.get_price_history",
        lambda db, asset, start_date, end_date: {start_date: SPOT_PER_OUNCE},
    )
    headers = registered_user["auth_headers"]
    bought = date.today() - timedelta(days=10)
    _create(client, headers, _vehicle(purchase_date=bought.isoformat()))
    _create(client, headers, _metal(purchase_date=bought.isoformat()))

    points = client.get("/api/v1/portfolio/history?period=1m", headers=headers).json()["points"]
    assert points[0]["date"] == bought.isoformat()
    first = Decimal(points[0]["total_physical_assets_value_base_currency"])
    assert first == Decimal("18750.00")
    last = points[-1]
    assert Decimal(last["total_physical_assets_value_base_currency"]) < first  # depreciation
    assert Decimal(last["total_net_worth"]) == Decimal(
        last["total_physical_assets_value_base_currency"]
    )
