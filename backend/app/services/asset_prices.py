"""
Asset price lookup: DB cache first, fallback to Alpha Vantage (stock/ETF) or
CoinGecko (crypto), dispatched by `Asset.asset_type`.

Prices are cached per (asset_id, date) in `asset_prices` so repeated lookups
for the same day don't hit the external API — this is what actually protects
Alpha Vantage's 25-requests/day free tier, not any client-side rate limiting.
"""

from datetime import date as date_
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Asset, AssetPrice


class AssetPriceUnavailable(Exception):
    pass


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
        price = _fetch_from_alpha_vantage(asset.symbol)
        source = "alpha_vantage"

    db.add(AssetPrice(asset_id=asset.id, price=price, date=on_date, source=source))
    db.commit()

    return price


def find_or_create_asset(db: Session, symbol: str, asset_type: str) -> Asset:
    symbol = symbol.upper()
    existing = (
        db.query(Asset)
        .filter(Asset.symbol == symbol, Asset.asset_type == asset_type)
        .first()
    )
    if existing is not None:
        return existing

    # Both providers price in USD for the tickers this app supports.
    asset = Asset(symbol=symbol, name=symbol, asset_type=asset_type, currency="USD")
    db.add(asset)
    db.flush()  # populates asset.id without committing yet — caller commits alongside the holding
    return asset


def search_assets(q: str, asset_type: str) -> list[dict]:
    """
    Only crypto gets live search (CoinGecko's /search is free and effectively
    unrate-limited). Stock/ETF have no autocomplete here: Alpha Vantage's free
    tier is 25 requests/day, and a search-as-you-type endpoint against it
    would burn that budget on typing alone — the user types the exact ticker
    instead, validated once at holding-creation time via get_price().
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


def _fetch_from_alpha_vantage(symbol: str) -> Decimal:
    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": symbol,
        "apikey": settings.alpha_vantage_api_key,
    }
    try:
        response = httpx.get(settings.alpha_vantage_api_base_url, params=params, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        price = data["Global Quote"]["05. price"]
        if not price:
            raise KeyError("empty price")
    except (httpx.HTTPError, KeyError) as exc:
        raise AssetPriceUnavailable(
            f"Could not fetch price for {symbol!r} from Alpha Vantage"
        ) from exc

    return Decimal(str(price))


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
