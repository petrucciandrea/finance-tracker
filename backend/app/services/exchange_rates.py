"""
Exchange rate lookup: DB cache first, fallback to the Frankfurter API.

Rates are cached per (from_currency, to_currency, date) in the `exchange_rates`
table so repeated lookups for the same day don't hit the external API, and so
historical transactions keep a durable, queryable record of the rate used.
"""

from datetime import date as date_
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ExchangeRate


class ExchangeRateUnavailable(Exception):
    pass


def get_rate(db: Session, from_currency: str, to_currency: str, on_date: date_) -> Decimal:
    """
    Return the conversion rate from_currency -> to_currency for the given date.
    Same-currency conversions short-circuit to 1 without touching the DB or API.
    """
    if from_currency == to_currency:
        return Decimal("1")

    cached = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.from_currency == from_currency,
            ExchangeRate.to_currency == to_currency,
            ExchangeRate.date == on_date,
        )
        .first()
    )
    if cached is not None:
        return Decimal(str(cached.rate))

    rate = _fetch_from_frankfurter(from_currency, to_currency, on_date)

    db.add(
        ExchangeRate(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            date=on_date,
            source="frankfurter",
        )
    )
    db.commit()

    return rate


def _fetch_from_frankfurter(from_currency: str, to_currency: str, on_date: date_) -> Decimal:
    """
    Frankfurter only covers fiat currencies (no crypto) and only has data from
    a certain historical start date onward. Callers dealing with crypto assets
    should use a different source (added in phase 3 alongside CoinGecko).
    """
    url = f"{settings.exchange_rate_api_base_url}/{on_date.isoformat()}"
    params = {"from": from_currency, "to": to_currency}

    try:
        response = httpx.get(url, params=params, timeout=5.0, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
        rate = data["rates"][to_currency]
    except (httpx.HTTPError, KeyError) as exc:
        raise ExchangeRateUnavailable(
            f"Could not fetch rate {from_currency}->{to_currency} for {on_date}"
        ) from exc

    return Decimal(str(rate))