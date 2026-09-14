"""
Exchange rate lookup: DB cache first, fallback to the Frankfurter API.

Rates are cached per (from_currency, to_currency, date) in the `exchange_rates`
table so repeated lookups for the same day don't hit the external API, and so
historical transactions keep a durable, queryable record of the rate used.

Cache writes `flush()` and leave the commit to the caller. They used to
commit the caller's session outright, which meant a cache miss halfway
through a multi-row write committed a half-finished state — and a handler
writing N linked pairs could end up persisting a pair with one leg. The
cost of the change is that a read-only endpoint must commit if it wants
the fetched rate to persist; the three that populate the cache on a read
path do so explicitly.
"""

from datetime import date as date_
from datetime import timedelta
from decimal import Decimal

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    # Not commit(): see the module docstring. The caller owns the transaction.
    db.flush()

    return rate


def get_rate_history(
    db: Session, from_currency: str, to_currency: str, start_date: date_, end_date: date_
) -> dict[date_, Decimal]:
    """
    Same one-call-backfills-the-range idea as `asset_prices.get_price_history`:
    Frankfurter's range endpoint returns every daily rate between two dates in
    a single response, so the portfolio value-over-time chart doesn't need one
    HTTP call per day to convert historical cash/holding balances.
    """
    if from_currency == to_currency:
        return {}  # caller short-circuits same-currency conversion to 1 itself

    cached_rows = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.from_currency == from_currency,
            ExchangeRate.to_currency == to_currency,
            ExchangeRate.date >= start_date,
            ExchangeRate.date <= end_date,
        )
        .all()
    )
    cached = {row.date: Decimal(str(row.rate)) for row in cached_rows}

    if cached and min(cached) <= start_date + timedelta(days=5):
        return cached

    url = f"{settings.exchange_rate_api_base_url}/{start_date.isoformat()}..{end_date.isoformat()}"
    params = {"from": from_currency, "to": to_currency}
    try:
        response = httpx.get(url, params=params, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        rates = response.json()["rates"]
    except (httpx.HTTPError, KeyError) as exc:
        raise ExchangeRateUnavailable(
            f"Could not fetch rate history {from_currency}->{to_currency}"
        ) from exc

    fetched = {
        date_.fromisoformat(day): Decimal(str(values[to_currency]))
        for day, values in rates.items()
        if to_currency in values
    }

    if fetched:
        stmt = (
            pg_insert(ExchangeRate)
            .values(
                [
                    {
                        "from_currency": from_currency,
                        "to_currency": to_currency,
                        "rate": rate,
                        "date": d,
                        "source": "frankfurter",
                    }
                    for d, rate in fetched.items()
                ]
            )
            .on_conflict_do_nothing(index_elements=["from_currency", "to_currency", "date"])
        )
        db.execute(stmt)
        db.flush()

    cached.update(fetched)
    return {d: r for d, r in cached.items() if start_date <= d <= end_date}


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