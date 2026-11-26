"""
The portfolio's allocation by asset class, region, sector and currency.

Three decisions worth knowing before reading the code:

- **Only pillar 4 is judged.** A holding that funds an emergency fund or a
  dated goal, or that holds the P.IVA tax provision, is money due within a
  few years: counted here, a money-market ETF parked for a down payment
  would make the portfolio read as cautious, and a target band would then
  suggest buying equities with it. Those positions are reported as
  `excluded_value` and nothing else.

- **What a product is made of comes from three places, per dimension:** the
  user's own weights, else the reference file shipped with the code
  (`app/data/asset_exposures.json`, researched figures with their source and
  date), else what the product's type implies (a stock is equity, crypto is
  crypto with no region). Whatever none of them covers is *unclassified*, a
  bucket of its own with a coverage percentage — never folded into a guess.

- **Sectors are over the equity part only.** A 50/50 equity/bond portfolio
  would otherwise show "tech 12%" and hide that tech is a quarter of the
  equities.

Valuation is cache-only (`net_worth.cached_holding_values`), so the alerts
banner can run this on every page. The portfolio page warms the caches
first (`warm_caches`), which is the only place this module calls out.
"""

import json
from dataclasses import dataclass, field
from datetime import date as date_
from datetime import timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    Account,
    Asset,
    AssetExposure,
    AssetProfile,
    PhysicalAsset,
    User,
)
from app.schemas import (
    EXPOSURE_BUCKETS,
    AllocationBucketValue,
    AllocationPosition,
    AllocationPositionKind,
    AssetExposureDimension,
    ExposureDimension,
    ExposureSource,
    ExposureWeight,
    PortfolioAllocation,
    SavingsGoalKind,
)
from app.schemas import Asset as AssetSchema
from app.services import asset_prices, flat_rate
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate
from app.services.net_worth import (
    account_balances,
    cached_holding_values,
    compute_holding_positions,
    latest_cached_prices,
    latest_cached_rate,
)
from app.services.physical_assets import (
    METAL_QUOTE_CURRENCY,
    TROY_OUNCE_GRAMS,
    metal_asset,
    metal_position,
    user_physical_assets_query,
)
from app.services.waterfall import active_sources, list_goals

REFERENCE_PATH = Path(__file__).resolve().parent.parent / "data" / "asset_exposures.json"
HUNDRED = Decimal("100")
# Weights older than this are flagged: index compositions drift, and a
# factsheet from two years ago can be ten points off on the US.
STALE_AFTER = timedelta(days=365)
# Below this share of classified value a rule doesn't judge the dimension.
MIN_COVERAGE = 90.0

# Crypto and metals have no fiat currency of their own: they are quoted in
# USD, but the quote is not what moves them, and counting gold as USD would
# make a cap on the dollar fire on a gold bar. "other" says "not EUR" without
# pretending to know which currency; a user who sees them otherwise overrides
# the product.
TYPE_DEFAULTS: dict[str, dict[str, dict[str, Decimal]]] = {
    "stock": {"asset_class": {"equity": HUNDRED}},
    "crypto": {
        "asset_class": {"crypto": HUNDRED},
        "region": {"not_applicable": HUNDRED},
        "currency": {"other": HUNDRED},
    },
    "metal": {
        "asset_class": {"commodity": HUNDRED},
        "region": {"not_applicable": HUNDRED},
        "currency": {"other": HUNDRED},
    },
}

NOT_APPLICABLE = "not_applicable"
# Cash on investment accounts, in the asset-class dimension only.
CASH_BUCKET = "cash"
INVESTMENT_ACCOUNT_TYPES = {"investment", "crypto_wallet"}


@dataclass
class Resolved:
    source: ExposureSource | None
    weights: dict[str, Decimal]
    as_of: date_ | None = None
    notes: str | None = None
    urls: list[str] = field(default_factory=list)


@dataclass
class Valued:
    kind: AllocationPositionKind
    label: str
    value: Decimal | None
    asset: Asset | None = None
    account_name: str | None = None
    currency: str | None = None  # cash only: the account's


# ---------------------------------------------------------------------------
# Exposures
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def reference_index() -> dict[tuple[str, str], dict]:
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    return {(row["symbol"], row["asset_type"]): row for row in data["assets"]}


def validate_weights(dimension: ExposureDimension, weights: list[ExposureWeight]) -> str | None:
    """The reason a set of weights is refused, or None."""
    allowed = EXPOSURE_BUCKETS[dimension.value]
    seen: set[str] = set()
    for w in weights:
        if w.bucket not in allowed:
            return f"Unknown bucket «{w.bucket}» for {dimension.value}"
        if w.bucket in seen:
            return f"Bucket «{w.bucket}» appears twice"
        seen.add(w.bucket)
    if sum((w.weight for w in weights), Decimal("0")) > HUNDRED:
        return "The weights add up to more than 100"
    return None


def resolve_exposures(
    db: Session, user: User, assets: list[Asset]
) -> dict[UUID, dict[str, Resolved]]:
    """Per asset, per dimension: the weights in force and where they came from."""
    ids = [a.id for a in assets]
    if not ids:
        return {}
    rows = (
        db.query(AssetExposure)
        .filter(AssetExposure.user_id == user.id, AssetExposure.asset_id.in_(ids))
        .all()
    )
    own: dict[tuple[UUID, str], dict[str, Decimal]] = {}
    for row in rows:
        own.setdefault((row.asset_id, row.dimension), {})[row.bucket] = Decimal(str(row.weight))
    profiles = {
        p.asset_id: p
        for p in db.query(AssetProfile).filter(
            AssetProfile.user_id == user.id, AssetProfile.asset_id.in_(ids)
        )
    }

    result: dict[UUID, dict[str, Resolved]] = {}
    for asset in assets:
        reference = reference_index().get((asset.symbol, asset.asset_type))
        per_dimension: dict[str, Resolved] = {}
        for dimension in ExposureDimension:
            key = dimension.value
            profile = profiles.get(asset.id)
            if (asset.id, key) in own:
                per_dimension[key] = Resolved(
                    ExposureSource.user,
                    own[(asset.id, key)],
                    profile.as_of if profile else None,
                    profile.notes if profile else None,
                )
            elif reference and key in reference["exposures"]:
                per_dimension[key] = Resolved(
                    ExposureSource.reference,
                    {b: Decimal(v) for b, v in reference["exposures"][key].items()},
                    date_.fromisoformat(reference["as_of"]),
                    reference.get("notes"),
                    list(reference.get("sources", [])),
                )
            elif key in TYPE_DEFAULTS.get(asset.asset_type, {}):
                per_dimension[key] = Resolved(
                    ExposureSource.default, dict(TYPE_DEFAULTS[asset.asset_type][key])
                )
            else:
                per_dimension[key] = Resolved(None, {})
        result[asset.id] = per_dimension
    return result


def to_dimension_schema(dimension: str, resolved: Resolved) -> AssetExposureDimension:
    return AssetExposureDimension(
        dimension=ExposureDimension(dimension),
        source=resolved.source,
        weights=_weights(resolved),
        as_of=resolved.as_of,
        notes=resolved.notes,
        source_urls=resolved.urls,
    )


def _weights(resolved: Resolved) -> list[ExposureWeight]:
    return [
        ExposureWeight(bucket=b, weight=w)
        for b, w in sorted(resolved.weights.items(), key=lambda kv: -kv[1])
    ]


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------


def warm_caches(db: Session, user: User) -> None:
    """
    Fetch today's prices and rates for what pillar 4 holds, so the
    cache-only valuation that follows is current. A failed lookup is left
    alone: the position then reads from its last stored price, or as
    unpriced. The caller commits.
    """
    today = date_.today()
    currencies: set[str] = set()
    for position in compute_holding_positions(db, user).values():
        if position["quantity"] <= 0:
            continue
        asset = position["asset"]
        currencies.add(asset.currency)
        try:
            asset_prices.get_price(db, asset, today)
        except asset_prices.AssetPriceUnavailable:
            pass
    metals = {m.metal for m in _held_metals(db, user) if m.metal}
    for metal in metals:
        asset = metal_asset(db, metal)
        if asset is None:
            continue
        currencies.add(METAL_QUOTE_CURRENCY)
        try:
            asset_prices.get_price(db, asset, today)
        except asset_prices.AssetPriceUnavailable:
            pass
    for currency in currencies:
        try:
            get_rate(db, currency, user.base_currency, today)
        except ExchangeRateUnavailable:
            pass


def _held_metals(db: Session, user: User) -> list[PhysicalAsset]:
    return [
        a
        for a in user_physical_assets_query(db, user).filter(PhysicalAsset.kind == "metal").all()
        if metal_position(a.movements).held_grams > 0
    ]


def _earmarked(db: Session, user: User) -> tuple[set[UUID], set[tuple[UUID, UUID]]]:
    """
    Cash accounts and holdings outside pillar 4: sources of an emergency
    fund or a medium-term goal, and the tax provision. A long-term goal's
    sources *are* pillar 4 and stay in.
    """
    cash: set[UUID] = set()
    holdings: set[tuple[UUID, UUID]] = set()
    for goal in list_goals(db, user, include_completed=False):
        if goal.kind == SavingsGoalKind.long_term.value:
            continue
        for source in active_sources(goal):
            if source.asset_id is None:
                cash.add(source.account_id)
            else:
                holdings.add((source.account_id, source.asset_id))
    for source in flat_rate.active_sources(db, user):
        if source.asset_id is None:
            cash.add(source.account_id)
        else:
            holdings.add((source.account_id, source.asset_id))
    return cash, holdings


def pillar4_positions(
    db: Session, user: User, on_date: date_, *, include_cash: bool
) -> tuple[list[Valued], Decimal]:
    """(valued positions, value left out as earmarked), cache-only."""
    accounts = {
        a.id: a
        for a in db.query(Account).filter(Account.user_id == user.id, Account.deleted_at.is_(None))
    }
    earmarked_cash, earmarked_holdings = _earmarked(db, user)
    positions = compute_holding_positions(db, user)
    values = cached_holding_values(db, user, positions, on_date)

    result: list[Valued] = []
    excluded = Decimal("0")
    for key, value in values.items():
        if key in earmarked_holdings:
            excluded += value or Decimal("0")
            continue
        account_id, _ = key
        asset = positions[key]["asset"]
        account = accounts.get(account_id)
        result.append(
            Valued(
                AllocationPositionKind.holding,
                asset.symbol,
                value,
                asset=asset,
                account_name=account.name if account else None,
            )
        )

    metals = _held_metals(db, user)
    if metals:
        usd_rate = latest_cached_rate(db, METAL_QUOTE_CURRENCY, user.base_currency, on_date)
        spot_assets = {m.metal: metal_asset(db, m.metal) for m in metals if m.metal}
        spots = latest_cached_prices(
            db, {a.id for a in spot_assets.values() if a is not None}, on_date
        )
        for metal in metals:
            spot_asset = spot_assets.get(metal.metal) if metal.metal else None
            spot = spots.get(spot_asset.id) if spot_asset else None
            fine_grams = metal_position(metal.movements).held_grams * Decimal(str(metal.purity))
            value = (
                fine_grams * spot / TROY_OUNCE_GRAMS * usd_rate
                if spot is not None and usd_rate is not None
                else None
            )
            result.append(Valued(AllocationPositionKind.metal, metal.name, value, asset=spot_asset))

    if include_cash:
        for balance in account_balances(db, user):
            account = accounts.get(balance.account_id)
            if (
                account is None
                or account.type not in INVESTMENT_ACCOUNT_TYPES
                or account.id in earmarked_cash
                or balance.balance_base_currency <= 0
            ):
                continue
            result.append(
                Valued(
                    AllocationPositionKind.cash,
                    f"Liquidità {account.name}",
                    balance.balance_base_currency,
                    account_name=account.name,
                    currency=account.currency,
                )
            )
    return result, excluded


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------


def _cash_weights(dimension: ExposureDimension, currency: str | None) -> dict[str, Decimal] | None:
    """Cash counts in asset class and currency; it has no region or sector."""
    if dimension == ExposureDimension.asset_class:
        return {CASH_BUCKET: HUNDRED}
    if dimension == ExposureDimension.currency:
        known = EXPOSURE_BUCKETS["currency"]
        return {currency if currency in known else "other": HUNDRED}
    return None


def allocation(
    db: Session,
    user: User,
    dimension: ExposureDimension,
    on_date: date_,
    *,
    include_cash: bool = False,
) -> PortfolioAllocation:
    valued, excluded = pillar4_positions(db, user, on_date, include_cash=include_cash)
    assets = list({v.asset.id: v.asset for v in valued if v.asset is not None}.values())
    resolved = resolve_exposures(db, user, assets)

    totals: dict[str, Decimal] = {}
    total = Decimal("0")
    classified = Decimal("0")
    outside = Decimal("0")
    stale = 0
    positions: list[AllocationPosition] = []

    for item in valued:
        if item.kind == AllocationPositionKind.cash:
            weights = _cash_weights(dimension, item.currency)
            if weights is None:
                continue
            exposure = Resolved(ExposureSource.default, weights)
        else:
            assert item.asset is not None
            exposure = resolved[item.asset.id][dimension.value]

        base = item.value
        if dimension == ExposureDimension.sector and item.kind != AllocationPositionKind.cash:
            # Over the equity part only. An unknown asset class could be all
            # equity: counted whole, as unclassified, it can't make the
            # sector coverage look better than it is.
            asset_class = resolved[item.asset.id]["asset_class"].weights  # type: ignore[union-attr]
            if asset_class and base is not None:
                equity = base * asset_class.get("equity", Decimal("0")) / HUNDRED
                outside += base - equity
                base = equity
            if asset_class and asset_class.get("equity", Decimal("0")) == 0:
                continue

        positions.append(
            AllocationPosition(
                kind=item.kind,
                label=item.label,
                asset=AssetSchema.model_validate(item.asset)
                if item.asset is not None and item.asset.asset_type != "metal"
                else None,
                account_name=item.account_name,
                value=_money(base) if base is not None else None,
                source=exposure.source,
                as_of=exposure.as_of,
                weights=_weights(exposure),
            )
        )
        if base is None:
            continue
        # Regions are over what has one: gold and crypto (`not_applicable`)
        # in the denominator would read a portfolio that is all US equity
        # plus some gold as "60% US" and let a country cap pass that is
        # really breached. Reported apart, like the non-equity part of
        # `sector`.
        no_region = exposure.weights.get(NOT_APPLICABLE, Decimal("0"))
        if dimension == ExposureDimension.region and no_region:
            outside += base * no_region / HUNDRED
        total += base - base * no_region / HUNDRED
        if exposure.as_of is not None and on_date - exposure.as_of > STALE_AFTER:
            stale += 1
        for bucket, weight in exposure.weights.items():
            if bucket == NOT_APPLICABLE:
                continue
            share = base * weight / HUNDRED
            totals[bucket] = totals.get(bucket, Decimal("0")) + share
            classified += share

    buckets = [
        AllocationBucketValue(
            bucket=bucket,
            value=_money(value),
            percentage=round(float(value / total * 100), 2) if total else 0.0,
        )
        for bucket, value in sorted(totals.items(), key=lambda kv: -kv[1])
    ]
    positions.sort(key=lambda p: -(p.value or Decimal("0")))
    return PortfolioAllocation(
        dimension=dimension,
        base_currency=user.base_currency,
        total=_money(total),
        classified_value=_money(classified),
        coverage=round(float(classified / total * 100), 1) if total else 0.0,
        buckets=buckets,
        unclassified_value=_money(total - classified),
        excluded_value=_money(excluded),
        outside_value=_money(outside),
        has_unpriced=any(v.value is None for v in valued),
        stale_count=stale,
        positions=positions,
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))
