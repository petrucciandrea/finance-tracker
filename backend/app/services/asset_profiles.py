"""
Sector and country of a single stock from Yahoo's `quoteSummary`, mapped to
the allocation's buckets — a *suggestion* for the exposure editor, never
saved by itself.

Stocks only: for ETFs Yahoo gives sector weights in its own taxonomy and no
countries at all, which is why their reference weights ship as a file.

The endpoint is unofficial and since 2023 wants a cookie plus a "crumb"
token. Both are fetched on first use and kept in process memory, like the
rate limiter; a 401 means they expired and they are fetched once more. Any
failure is `AssetProfileUnavailable`, and the editor simply stays manual.
"""

from decimal import Decimal
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.models import Asset
from app.schemas import EXPOSURE_BUCKETS, ExposureDimension, ExposureSuggestion, ExposureWeight

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; finance-tracker/1.0)"}
_session: dict[str, httpx.Client] = {}
_crumb: dict[str, str] = {}

# Yahoo's sector names (Morningstar's) → GICS. Close, not exact: Yahoo puts
# Alphabet and Meta under Communication Services like GICS, but files Visa
# under Financial Services where GICS (since 2023) agrees, so the mismatch
# is mostly at the margins.
SECTOR_MAP = {
    "Technology": "information_technology",
    "Financial Services": "financials",
    "Healthcare": "health_care",
    "Consumer Cyclical": "consumer_discretionary",
    "Communication Services": "communication_services",
    "Industrials": "industrials",
    "Consumer Defensive": "consumer_staples",
    "Energy": "energy",
    "Basic Materials": "materials",
    "Utilities": "utilities",
    "Real Estate": "real_estate",
}

# Country → region, MSCI's developed/emerging split (Korea is emerging).
_EUROPE = {
    "Austria",
    "Belgium",
    "Denmark",
    "Finland",
    "France",
    "Germany",
    "Ireland",
    "Netherlands",
    "Norway",
    "Portugal",
    "Spain",
    "Sweden",
    "Switzerland",
    "Luxembourg",
    "Israel",
}
_PACIFIC = {"Australia", "Hong Kong", "New Zealand", "Singapore"}
_EMERGING = {
    "Brazil",
    "Chile",
    "China",
    "Colombia",
    "Czech Republic",
    "Egypt",
    "Greece",
    "Hungary",
    "India",
    "Indonesia",
    "Kuwait",
    "Malaysia",
    "Mexico",
    "Peru",
    "Philippines",
    "Poland",
    "Qatar",
    "Saudi Arabia",
    "South Africa",
    "South Korea",
    "Taiwan",
    "Thailand",
    "Turkey",
    "United Arab Emirates",
}


def region_of(country: str | None) -> str | None:
    if not country:
        return None
    if country in ("United States", "Canada"):
        return "north_america"
    if country == "Italy":
        return "italy"
    if country == "United Kingdom":
        return "united_kingdom"
    if country == "Japan":
        return "japan"
    if country in _PACIFIC:
        return "pacific_ex_japan"
    if country in _EUROPE:
        return "europe_ex_italy"
    if country in _EMERGING:
        return "emerging"
    return None


class AssetProfileUnavailable(Exception):
    pass


def _refresh_session() -> None:
    client = httpx.Client(headers=_HEADERS, timeout=5.0, follow_redirects=True)
    # fc.yahoo.com answers 404 but sets the cookie the crumb is bound to.
    client.get(settings.yahoo_cookie_url)
    crumb = client.get(settings.yahoo_crumb_url)
    crumb.raise_for_status()
    _session["client"] = client
    _crumb["value"] = crumb.text.strip()


def _fetch_profile(symbol: str) -> dict:
    for attempt in range(2):
        if "client" not in _session or attempt == 1:
            _refresh_session()
        client = _session["client"]
        response = client.get(
            f"{settings.yahoo_quote_summary_url}/{quote(symbol, safe='')}",
            params={"modules": "assetProfile", "crumb": _crumb["value"]},
        )
        if response.status_code == 401 and attempt == 0:
            continue
        response.raise_for_status()
        result = response.json()["quoteSummary"]["result"]
        return result[0]["assetProfile"] if result else {}
    return {}


def suggest(asset: Asset) -> ExposureSuggestion:
    if asset.asset_type != "stock":
        raise AssetProfileUnavailable("Suggestions are for single stocks only")
    try:
        profile = _fetch_profile(asset.symbol)
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise AssetProfileUnavailable(str(exc)) from exc

    sector = profile.get("sector")
    country = profile.get("country")
    weights: dict[ExposureDimension, list[ExposureWeight]] = {
        ExposureDimension.asset_class: [ExposureWeight(bucket="equity", weight=Decimal(100))],
    }
    if sector in SECTOR_MAP:
        weights[ExposureDimension.sector] = [
            ExposureWeight(bucket=SECTOR_MAP[sector], weight=Decimal(100))
        ]
    region = region_of(country)
    if region:
        weights[ExposureDimension.region] = [ExposureWeight(bucket=region, weight=Decimal(100))]
    currency = asset.currency if asset.currency in EXPOSURE_BUCKETS["currency"] else "other"
    weights[ExposureDimension.currency] = [ExposureWeight(bucket=currency, weight=Decimal(100))]
    return ExposureSuggestion(
        asset_id=asset.id, raw_sector=sector, raw_country=country, weights=weights
    )
