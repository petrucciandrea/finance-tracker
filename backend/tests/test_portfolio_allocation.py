"""
The portfolio's allocation (pillar 4 only) and the per-product weights
behind it: the user's own, the reference file's, or the type's default.

Every product is priced at 50 EUR by the patched provider, so a position's
value is its quantity × 50.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.services.asset_prices import AssetPriceUnavailable

ALLOCATION_URL = "/api/v1/portfolio/allocation"
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


@pytest.fixture
def broker(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Broker",
            "type": "investment",
            "currency": "EUR",
            "starting_balance": "10000",
        },
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _buy(
    client: TestClient, headers: dict, account_id: str, symbol: str, quantity: str, type_="etf"
) -> str:
    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "account_id": account_id,
            "symbol": symbol,
            "asset_type": type_,
            "type": "buy",
            "quantity": quantity,
            "price": "50.00",
            "date": TODAY.isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["asset"]["id"]


def _allocation(client: TestClient, headers: dict, dimension: str, **params) -> dict:
    response = client.get(
        ALLOCATION_URL, params={"dimension": dimension, **params}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _pct(body: dict, bucket: str) -> float:
    return next((b["percentage"] for b in body["buckets"] if b["bucket"] == bucket), 0.0)


def test_a_known_etf_reads_from_the_reference_file(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "VWCE.DE", "10")

    body = _allocation(client, headers, "region")

    assert Decimal(body["total"]) == Decimal("500.00")
    assert body["coverage"] == 100.0
    assert _pct(body, "north_america") == 65.6
    assert body["positions"][0]["source"] == "reference"


def test_an_unknown_etf_is_unclassified_and_a_stock_is_equity(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "ZZZZ.DE", "10")  # an ETF the file doesn't know
    _buy(client, headers, broker["id"], "TSLA", "10", type_="stock")

    body = _allocation(client, headers, "asset_class")

    # A bond ETF and an equity ETF look the same from the outside: no guess.
    assert body["coverage"] == 50.0
    assert Decimal(body["unclassified_value"]) == Decimal("500.00")
    assert _pct(body, "equity") == 50.0


def test_sectors_are_measured_on_the_equity_part_only(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "QDVE.DE", "10")  # 500, all IT
    _buy(client, headers, broker["id"], "XEON.DE", "10")  # 500, money market

    body = _allocation(client, headers, "sector")

    # Over the whole portfolio IT would read 50%; over the equities it is all of them.
    assert Decimal(body["total"]) == Decimal("500.00")
    assert _pct(body, "information_technology") == 100.0


def test_the_users_weights_override_the_reference(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    asset_id = _buy(client, headers, broker["id"], "VWCE.DE", "10")
    url = f"/api/v1/portfolio/assets/{asset_id}/exposures/region"

    saved = client.put(
        url,
        json={
            "weights": [
                {"bucket": "north_america", "weight": "60"},
                {"bucket": "emerging", "weight": "30"},
            ]
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    region = _allocation(client, headers, "region")
    assert _pct(region, "north_america") == 60.0
    assert region["coverage"] == 90.0  # the 10 left out is unclassified
    assert region["positions"][0]["source"] == "user"

    assert client.delete(url, headers=headers).status_code == 200
    assert _pct(_allocation(client, headers, "region"), "north_america") == 65.6


@pytest.mark.parametrize(
    "weights",
    [
        [{"bucket": "north_america", "weight": "70"}, {"bucket": "emerging", "weight": "40"}],
        [{"bucket": "atlantis", "weight": "10"}],
        [{"bucket": "italy", "weight": "10"}, {"bucket": "italy", "weight": "20"}],
        [],
    ],
)
def test_invalid_weights_are_refused(
    client: TestClient, registered_user: dict, broker: dict, weights: list
) -> None:
    headers = registered_user["auth_headers"]
    asset_id = _buy(client, headers, broker["id"], "VWCE.DE", "10")

    response = client.put(
        f"/api/v1/portfolio/assets/{asset_id}/exposures/region",
        json={"weights": weights},
        headers=headers,
    )

    assert response.status_code == 422


def test_a_product_the_user_never_traded_is_not_found(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "altro@example.com",
            "password": "Sicura-Password-123",
            "base_currency": "EUR",
            "accept_terms": True,
        },
    )
    assert other.status_code in (200, 201), other.text
    asset_id = _buy(client, registered_user["auth_headers"], broker["id"], "VWCE.DE", "1")
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "altro@example.com", "password": "Sicura-Password-123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get(f"/api/v1/portfolio/assets/{asset_id}/exposures", headers=headers)

    assert response.status_code == 404


def test_holdings_earmarked_for_a_dated_goal_are_left_out(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    parked = _buy(client, headers, broker["id"], "XEON.DE", "20")  # 1000
    _buy(client, headers, broker["id"], "VWCE.DE", "10")  # 500
    goal = client.post(
        "/api/v1/planning/goals",
        json={
            "name": "Anticipo casa",
            "kind": "medium_term",
            "target_mode": "fixed_amount",
            "target_amount": "20000",
            "target_date": f"{TODAY.year + 3}-06-01",
        },
        headers=headers,
    ).json()
    mapped = client.post(
        f"/api/v1/planning/goals/{goal['id']}/sources",
        json={"account_id": broker["id"], "asset_id": parked},
        headers=headers,
    )
    assert mapped.status_code == 201, mapped.text

    body = _allocation(client, headers, "asset_class")

    # Counted, the down payment would make the portfolio two-thirds cash-like.
    assert Decimal(body["excluded_value"]) == Decimal("1000.00")
    assert Decimal(body["total"]) == Decimal("500.00")
    assert _pct(body, "equity") == 100.0


def test_uninvested_broker_cash_counts_only_when_asked(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "VWCE.DE", "10")  # 500; 9500 cash left

    without = _allocation(client, headers, "asset_class")
    with_cash = _allocation(client, headers, "asset_class", include_cash="true")

    assert Decimal(without["total"]) == Decimal("500.00")
    assert Decimal(with_cash["total"]) == Decimal("10000.00")
    assert _pct(with_cash, "cash") == 95.0


def test_a_provider_outage_falls_back_to_the_last_price(
    client: TestClient, registered_user: dict, broker: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "VWCE.DE", "10")

    def outage(symbol):
        raise AssetPriceUnavailable(symbol)

    monkeypatch.setattr("app.services.asset_prices._fetch_from_yahoo_finance", outage)
    body = _allocation(client, headers, "asset_class")

    assert Decimal(body["total"]) == Decimal("500.00")
    assert body["has_unpriced"] is False


def test_a_stock_suggestion_is_mapped_and_not_saved(
    client: TestClient, registered_user: dict, broker: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = registered_user["auth_headers"]
    asset_id = _buy(client, headers, broker["id"], "ASML", "1", type_="stock")
    monkeypatch.setattr(
        "app.services.asset_profiles._fetch_profile",
        lambda symbol: {"sector": "Technology", "country": "Netherlands"},
    )

    response = client.get(
        f"/api/v1/portfolio/assets/{asset_id}/exposure-suggestion", headers=headers
    )

    assert response.status_code == 200, response.text
    weights = response.json()["weights"]
    assert weights["sector"] == [{"bucket": "information_technology", "weight": "100"}]
    assert weights["region"] == [{"bucket": "europe_ex_italy", "weight": "100"}]
    region = _allocation(client, headers, "region")
    assert region["coverage"] == 0.0  # still nothing saved


def test_no_suggestion_for_an_etf(client: TestClient, registered_user: dict, broker: dict) -> None:
    headers = registered_user["auth_headers"]
    asset_id = _buy(client, headers, broker["id"], "VWCE.DE", "1")

    response = client.get(
        f"/api/v1/portfolio/assets/{asset_id}/exposure-suggestion", headers=headers
    )

    assert response.status_code == 502


def test_regions_leave_out_what_has_no_region(
    client: TestClient, registered_user: dict, broker: dict
) -> None:
    headers = registered_user["auth_headers"]
    _buy(client, headers, broker["id"], "QDVE.DE", "10")  # 500, all North America
    _buy(client, headers, broker["id"], "XEON.DE", "10")  # 500, no region

    body = _allocation(client, headers, "region")

    # Counted in, the money market would halve a concentration that is total.
    assert _pct(body, "north_america") == 100.0
    assert Decimal(body["total"]) == Decimal("500.00")
    assert Decimal(body["outside_value"]) == Decimal("500.00")
    assert body["coverage"] == 100.0
