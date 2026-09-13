"""
Asset price lookup: DB cache first, fallback to Yahoo Finance (stock/ETF) or
CoinGecko (crypto), dispatched by `Asset.asset_type`.

Prices are cached per (asset_id, date) in `asset_prices` so repeated lookups
for the same day don't hit the external API — Yahoo's chart endpoint is
unofficial (no API key, no documented quota, no support guarantee) and the
DB cache is what keeps this app from hammering it on every page load.
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_
from decimal import Decimal

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Asset, AssetPrice, Currency


class AssetPriceUnavailable(Exception):
    pass


# Yahoo's chart endpoint 403s requests with no browser-like User-Agent.
_YAHOO_FINANCE_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; finance-tracker/1.0)"}


def _yahoo_price(value: float) -> Decimal:
    # Yahoo's underlying OHLC data is float32, so `str(value)` on the raw
    # JSON float carries trailing noise (e.g. 315.3399963378906 for what is
    # actually $315.34) — round to the cent before converting to Decimal.
    return Decimal(str(round(value, 2)))


# CoinGecko prices by *coin id*, not ticker (e.g. "bitcoin", not "BTC") — a
# small static map for the common coins a personal user is likely to hold.
# Extending this to arbitrary altcoins would mean caching CoinGecko's
# /coins/list once; out of scope for v1.
SYMBOL_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
}


def get_price(db: Session, asset: Asset, on_date: date_) -> Decimal:
    """Return asset's price (in asset.currency) on the given date."""
    cached = (
        db.query(AssetPrice)
        .filter(AssetPrice.asset_id == asset.id, AssetPrice.date == on_date)
        .first()
    )
    if cached is not None:
        return Decimal(str(cached.price))

    if asset.asset_type == "crypto":
        price = _fetch_from_coingecko(asset.symbol)
        source = "coingecko"
    else:
        price = _fetch_from_yahoo_finance(asset.symbol)
        source = "yahoo_finance"

    db.add(AssetPrice(asset_id=asset.id, price=price, date=on_date, source=source))
    db.commit()

    return price


def get_price_history(
    db: Session, asset: Asset, start_date: date_, end_date: date_
) -> dict[date_, Decimal]:
    """
    Return {date: price} for the given range, backfilling from the provider
    in a single call when the range isn't already cached.

    `get_price`'s Yahoo Finance/CoinGecko calls only ever return *today's*
    price — they can't answer "what was this worth on 2026-03-01", which the
    portfolio value-over-time chart needs. Both providers' chart/history
    endpoints return an asset's whole requested range in one call, so we
    fetch once and cache every date returned rather than one request per day.
    """
    cached_rows = (
        db.query(AssetPrice)
        .filter(
            AssetPrice.asset_id == asset.id,
            AssetPrice.date >= start_date,
            AssetPrice.date <= end_date,
        )
        .all()
    )
    cached = {row.date: Decimal(str(row.price)) for row in cached_rows}

    # Trading calendars have gaps (weekends, holidays) so we can't require
    # every single date to be cached — treat "we already have something
    # within a few days of the start of the range" as full coverage.
    if cached and min(cached) <= start_date + timedelta(days=5):
        return cached

    if asset.asset_type == "crypto":
        fetched = _fetch_price_history_from_coingecko(asset.symbol, start_date, end_date)
        source = "coingecko"
    else:
        fetched = _fetch_price_history_from_yahoo_finance(asset.symbol, start_date, end_date)
        source = "yahoo_finance"

    if fetched:
        stmt = (
            pg_insert(AssetPrice)
            .values(
                [
                    {"asset_id": asset.id, "price": price, "date": d, "source": source}
                    for d, price in fetched.items()
                ]
            )
            .on_conflict_do_nothing(index_elements=["asset_id", "date"])
        )
        db.execute(stmt)
        db.commit()

    cached.update(fetched)
    return {d: p for d, p in cached.items() if start_date <= d <= end_date}


def _fetch_price_history_from_yahoo_finance(
    symbol: str, start_date: date_, end_date: date_
) -> dict[date_, Decimal]:
    period1 = int(datetime.combine(start_date, datetime.min.time(), tzinfo=UTC).timestamp())
    # Yahoo's `period2` excludes same-day data in practice — pad by a day so
    # `end_date` itself comes back.
    period2_date = end_date + timedelta(days=1)
    period2 = int(datetime.combine(period2_date, datetime.min.time(), tzinfo=UTC).timestamp())

    try:
        response = httpx.get(
            f"{settings.yahoo_finance_api_base_url}/{symbol}",
            params={"interval": "1d", "period1": period1, "period2": period2},
            headers=_YAHOO_FINANCE_HEADERS,
            timeout=10.0,
        )
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        raise AssetPriceUnavailable(
            f"Could not fetch price history for {symbol!r} from Yahoo Finance"
        ) from exc

    prices: dict[date_, Decimal] = {}
    # strict=False: an untrusted, unofficial API occasionally returning
    # mismatched array lengths should degrade gracefully, not crash the request.
    for timestamp, close in zip(timestamps, closes, strict=False):
        if close is None:  # Yahoo returns null for gaps within the requested range
            continue
        day = datetime.fromtimestamp(timestamp, tz=UTC).date()
        prices[day] = _yahoo_price(close)
    return prices


def _fetch_price_history_from_coingecko(
    symbol: str, start_date: date_, end_date: date_
) -> dict[date_, Decimal]:
    coin_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
    if coin_id is None:
        raise AssetPriceUnavailable(
            f"Unknown crypto symbol {symbol!r} — not in the supported coin map"
        )

    params: dict[str, str] = {
        "vs_currency": "usd",
        "from": str(int(datetime.combine(start_date, datetime.min.time(), tzinfo=UTC).timestamp())),
        "to": str(int(datetime.combine(end_date, datetime.min.time(), tzinfo=UTC).timestamp())),
    }
    if settings.coingecko_api_key:
        params["x_cg_demo_api_key"] = settings.coingecko_api_key

    try:
        response = httpx.get(
            f"{settings.coingecko_api_base_url}/coins/{coin_id}/market_chart/range",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        raw_prices = response.json()["prices"]
    except (httpx.HTTPError, KeyError) as exc:
        raise AssetPriceUnavailable(
            f"Could not fetch price history for {symbol!r} from CoinGecko"
        ) from exc

    result: dict[date_, Decimal] = {}
    for timestamp_ms, price in raw_prices:
        day = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()
        result[day] = Decimal(str(price))  # later points win ties within the same day
    return result


def find_or_create_asset(db: Session, symbol: str, asset_type: str) -> Asset:
    symbol = symbol.upper()
    existing = (
        db.query(Asset)
        .filter(Asset.symbol == symbol, Asset.asset_type == asset_type)
        .first()
    )
    if existing is not None:
        return existing

    # CoinGecko is always queried in USD, but Yahoo Finance prices a ticker
    # in whatever currency its home exchange trades in — EUR for VWCE.DE on
    # Xetra, GBP for a London listing, etc. Ask it rather than assuming USD.
    currency = "USD" if asset_type == "crypto" else _fetch_currency_from_yahoo_finance(symbol)
    if db.get(Currency, currency) is None:
        raise AssetPriceUnavailable(
            f"{symbol!r} is priced in {currency!r}, which this app doesn't support yet"
        )

    asset = Asset(symbol=symbol, name=symbol, asset_type=asset_type, currency=currency)
    db.add(asset)
    db.flush()  # populates asset.id without committing yet — caller commits alongside the holding
    return asset


def _fetch_currency_from_yahoo_finance(symbol: str) -> str:
    try:
        response = httpx.get(
            f"{settings.yahoo_finance_api_base_url}/{symbol}",
            params={"interval": "1d", "range": "1d"},
            headers=_YAHOO_FINANCE_HEADERS,
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()["chart"]["result"][0]["meta"]["currency"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        raise AssetPriceUnavailable(
            f"Could not determine the trading currency for {symbol!r} from Yahoo Finance"
        ) from exc


def search_assets(q: str, asset_type: str) -> list[dict]:
    """
    Only crypto gets live search (CoinGecko's /search is free and effectively
    unrate-limited). Stock/ETF have no autocomplete here: Yahoo's chart
    endpoint is unofficial with no documented quota, and a search-as-you-type
    endpoint against it risks getting the app's IP rate-limited or blocked —
    the user types the exact ticker instead, validated once at
    transaction-creation time via get_price().
    """
    if asset_type != "crypto":
        return []

    try:
        response = httpx.get(
            f"{settings.coingecko_api_base_url}/search", params={"query": q}, timeout=5.0
        )
        response.raise_for_status()
        coins = response.json().get("coins", [])
    except httpx.HTTPError:
        return []

    return [
        {"symbol": coin["symbol"].upper(), "name": coin["name"], "asset_type": "crypto"}
        for coin in coins[:10]
    ]


def _fetch_from_yahoo_finance(symbol: str) -> Decimal:
    try:
        response = httpx.get(
            f"{settings.yahoo_finance_api_base_url}/{symbol}",
            params={"interval": "1d", "range": "1d"},
            headers=_YAHOO_FINANCE_HEADERS,
            timeout=5.0,
        )
        response.raise_for_status()
        price = response.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        raise AssetPriceUnavailable(
            f"Could not fetch price for {symbol!r} from Yahoo Finance"
        ) from exc

    return _yahoo_price(price)


def _fetch_from_coingecko(symbol: str) -> Decimal:
    coin_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
    if coin_id is None:
        raise AssetPriceUnavailable(
            f"Unknown crypto symbol {symbol!r} — not in the supported coin map"
        )

    params = {"ids": coin_id, "vs_currencies": "usd"}
    if settings.coingecko_api_key:
        params["x_cg_demo_api_key"] = settings.coingecko_api_key

    try:
        response = httpx.get(
            f"{settings.coingecko_api_base_url}/simple/price", params=params, timeout=5.0
        )
        response.raise_for_status()
        price = response.json()[coin_id]["usd"]
    except (httpx.HTTPError, KeyError) as exc:
        raise AssetPriceUnavailable(f"Could not fetch price for {symbol!r} from CoinGecko") from exc

    return Decimal(str(price))
