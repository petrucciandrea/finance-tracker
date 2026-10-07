"""
Valuation of physical assets: vehicles and precious metals.

Neither has a market quote of its own, so both are estimates — and both are
deliberately conservative:

- A vehicle loses a fixed share of its value per year, compounded daily
  from its anchor: the purchase, or the latest manual valuation on or
  before the date asked about. A valuation re-anchors the curve rather than
  overriding one point, so the estimate keeps sliding after an appraisal
  instead of freezing at it.
- A metal position is worth its fine content (grams held × purity) at
  today's spot price. That includes jewellery: craftsmanship and brand have
  no dependable resale market — a "compro oro" pays melt value — so
  counting them would inflate net worth with money nobody would actually
  pay. The grams held come from its buy/sell movements, costed at weighted
  average like a portfolio holding.

Spot prices are COMEX/NYMEX futures from Yahoo Finance, in USD per troy
ounce, cached through the same `assets`/`asset_prices` rows as portfolio
holdings (the migration seeds one `metal` asset per metal).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date as date_
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Query, Session

from app.models import Asset, PhysicalAsset, PhysicalAssetMovement, Transaction, User
from app.schemas import (
    MetalForm,
    MetalMovement,
    MetalMovementType,
    PhysicalAssetKind,
    PhysicalAssetWithValue,
    PreciousMetal,
    VehicleType,
)
from app.schemas import PhysicalAssetValuation as PhysicalAssetValuationSchema
from app.services import asset_prices as asset_prices_service
from app.services.asset_prices import AssetPriceUnavailable
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate

TROY_OUNCE_GRAMS = Decimal("31.1034768")
DAYS_PER_YEAR = Decimal("365.25")
METAL_SYMBOLS = {"gold": "GC=F", "silver": "SI=F", "platinum": "PL=F"}
# Spot quotes are in USD; also the currency of the seeded `metal` assets.
METAL_QUOTE_CURRENCY = "USD"

_CENT = Decimal("0.01")


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def user_physical_assets_query(db: Session, user: User) -> Query:
    return db.query(PhysicalAsset).filter(
        PhysicalAsset.user_id == user.id, PhysicalAsset.deleted_at.is_(None)
    )


def metal_asset(db: Session, metal: str) -> Asset | None:
    return (
        db.query(Asset)
        .filter(Asset.symbol == METAL_SYMBOLS[metal], Asset.asset_type == "metal")
        .first()
    )


def is_held_on(asset: PhysicalAsset, on_date: date_) -> bool:
    """Vehicles only — a metal position's holding is `grams_held_on`."""
    # The sale date itself is excluded: on that day the money is already in
    # the account (or in the user's pocket), so counting the object too
    # would double it.
    return (
        asset.purchase_date is not None
        and asset.purchase_date <= on_date
        and (asset.sold_at is None or on_date < asset.sold_at)
    )


def acquired_on(asset: PhysicalAsset) -> date_ | None:
    if asset.kind == "vehicle":
        return asset.purchase_date
    return min((m.date for m in asset.movements), default=None)


def vehicle_value(asset: PhysicalAsset, on_date: date_) -> Decimal:
    """Estimated value in `asset.currency` on `on_date` (assumed held then)."""
    anchor_date = asset.purchase_date
    anchor_value = Decimal(str(asset.purchase_price))
    for valuation in asset.valuations:  # ordered by date
        if valuation.date > on_date:
            break
        anchor_date, anchor_value = valuation.date, Decimal(str(valuation.value))

    assert anchor_date is not None  # a vehicle always has one (DB CHECK)
    years = Decimal(max((on_date - anchor_date).days, 0)) / DAYS_PER_YEAR
    retained = (Decimal("1") - Decimal(str(asset.depreciation_rate))) ** years
    return _money(anchor_value * retained)


class MovementLike(Protocol):
    type: str
    date: date_
    weight_grams: Decimal
    price_base_currency: Decimal | None


class OversoldError(ValueError):
    def __init__(self, on_date: date_, held: Decimal, wanted: Decimal) -> None:
        super().__init__(
            f"Cannot sell {wanted.normalize():f} g on {on_date.isoformat()}"
            f" — only {held.normalize():f} g held then"
        )


@dataclass
class MetalPosition:
    held_grams: Decimal
    # Cost of the grams held, in base currency; None when any of them came
    # without a price (a gift) — an average over a made-up zero would lie.
    cost_base: Decimal | None
    realized_pnl_base: Decimal | None
    last_sell: date_ | None


def _chronological(movements: Iterable[MovementLike]) -> list[MovementLike]:
    # Day granularity: on a tied date buys go first, the only order that
    # can't spuriously sell from a position that's still empty — the same
    # rule as compute_holding_positions. Same-type ties don't affect the
    # average cost, so no further tiebreaker is needed.
    return sorted(movements, key=lambda m: (m.date, 0 if m.type == "buy" else 1))


def metal_position(movements: Iterable[MovementLike]) -> MetalPosition:
    """
    Walk the movements at weighted-average cost. Raises OversoldError if a
    sale ever exceeds what was held on its date — the router runs this on
    the would-be ledger before every write, so a stored ledger never does.
    """
    held = Decimal("0")
    cost: Decimal | None = Decimal("0")
    realized: Decimal | None = Decimal("0")
    last_sell = None

    for movement in _chronological(movements):
        grams = Decimal(str(movement.weight_grams))
        price = (
            Decimal(str(movement.price_base_currency))
            if movement.price_base_currency is not None
            else None
        )
        if movement.type == "buy":
            if held == 0:
                cost = Decimal("0")  # an emptied position starts its cost afresh
            held += grams
            cost = cost + price if cost is not None and price is not None else None
            continue

        if grams > held:
            raise OversoldError(movement.date, held, grams)
        if cost is not None and price is not None and realized is not None:
            sold_cost = cost * grams / held
            cost -= sold_cost
            realized += price - sold_cost
        else:
            realized = None
        held -= grams
        last_sell = movement.date

    return MetalPosition(
        held_grams=held,
        cost_base=cost if held > 0 else None,
        realized_pnl_base=realized,
        last_sell=last_sell,
    )


def grams_held_on(asset: PhysicalAsset, on_date: date_) -> Decimal:
    # A sale on `on_date` already counts, matching `is_held_on`.
    return sum(
        (
            Decimal(str(m.weight_grams)) * (1 if m.type == "buy" else -1)
            for m in asset.movements
            if m.date <= on_date
        ),
        Decimal("0"),
    )


def metal_value_usd(fine_grams: Decimal, spot_per_ounce_usd: Decimal) -> Decimal:
    return fine_grams * spot_per_ounce_usd / TROY_OUNCE_GRAMS


def physical_assets_with_value(
    db: Session, user: User, *, include_sold: bool = False
) -> list[PhysicalAssetWithValue]:
    """
    Every asset valued today, in the user's base currency.

    One spot lookup per metal and one rate lookup per currency, however many
    objects share them. Like `holdings_with_value` this may fill the price
    and rate caches without committing; the caller commits. A lookup that
    fails leaves the affected values at None instead of failing the whole
    request — a Yahoo outage shouldn't take the net-worth page down.
    """
    assets = user_physical_assets_query(db, user).order_by(PhysicalAsset.created_at).all()
    valued = value_physical_assets(db, user, assets)
    # Filtered after valuing: an emptied metal position is "sold" only
    # once its movements have been walked.
    if not include_sold:
        valued = [a for a in valued if a.sold_at is None]
    return sorted(valued, key=lambda a: a.purchase_date)


def value_physical_assets(
    db: Session, user: User, assets: list[PhysicalAsset]
) -> list[PhysicalAssetWithValue]:
    today = date_.today()
    rates: dict[str, Decimal | None] = {}

    def rate_to_base(currency: str) -> Decimal | None:
        if currency not in rates:
            try:
                rates[currency] = get_rate(db, currency, user.base_currency, today)
            except ExchangeRateUnavailable:
                rates[currency] = None
        return rates[currency]

    spots: dict[str, Decimal | None] = {}

    def spot_per_ounce(metal: str) -> Decimal | None:
        if metal not in spots:
            asset = metal_asset(db, metal)
            try:
                spots[metal] = (
                    asset_prices_service.get_price(db, asset, today) if asset else None
                )
            except AssetPriceUnavailable:
                spots[metal] = None
        return spots[metal]

    result = []
    for asset in assets:
        value_base: Decimal | None = None
        pnl: Decimal | None = None
        fine_grams: Decimal | None = None
        spot_per_gram_base: Decimal | None = None
        position: MetalPosition | None = None

        if asset.kind == "vehicle":
            rate = rate_to_base(asset.currency)
            if is_held_on(asset, today) and rate is not None:
                value_base = _money(vehicle_value(asset, today) * rate)
            realized_or_current = asset.sale_price_base_currency if asset.sold_at else value_base
            cost = asset.purchase_price_base_currency
            if cost is not None and realized_or_current is not None:
                pnl = _money(Decimal(str(realized_or_current)) - Decimal(str(cost)))
        else:
            position = metal_position(asset.movements)
            fine_grams = position.held_grams * Decimal(str(asset.purity))
            # Never None for a metal (DB CHECK); the guard is for the type checker.
            spot = spot_per_ounce(asset.metal) if asset.metal else None
            usd_rate = rate_to_base(METAL_QUOTE_CURRENCY)
            if spot is not None and usd_rate is not None:
                spot_per_gram_base = _money(spot / TROY_OUNCE_GRAMS * usd_rate)
                if position.held_grams > 0:
                    value_base = _money(metal_value_usd(fine_grams, spot) * usd_rate)
            if value_base is not None and position.cost_base is not None:
                pnl = _money(value_base - position.cost_base)

        if position is None:
            cost_shown = asset.purchase_price_base_currency
            sold_at = asset.sold_at
            realized = None
        else:
            cost_shown = _money(position.cost_base) if position.cost_base is not None else None
            sold_at = position.last_sell if position.held_grams == 0 else None
            realized = (
                _money(position.realized_pnl_base)
                if position.realized_pnl_base is not None
                else None
            )

        result.append(
            PhysicalAssetWithValue(
                id=asset.id,
                kind=PhysicalAssetKind(asset.kind),
                name=asset.name,
                notes=asset.notes,
                currency=asset.currency,
                purchase_date=acquired_on(asset) or asset.created_at.date(),
                purchase_price=asset.purchase_price,
                purchase_price_base_currency=cost_shown,
                purchase_account_id=_leg_account_id(asset.purchase_transaction),
                sold_at=sold_at,
                sale_price=asset.sale_price,
                sale_price_base_currency=asset.sale_price_base_currency,
                sale_account_id=_leg_account_id(asset.sale_transaction),
                vehicle_type=VehicleType(asset.vehicle_type) if asset.vehicle_type else None,
                depreciation_rate=asset.depreciation_rate,
                valuations=[
                    PhysicalAssetValuationSchema.model_validate(v) for v in asset.valuations
                ],
                metal=PreciousMetal(asset.metal) if asset.metal else None,
                metal_form=MetalForm(asset.metal_form) if asset.metal_form else None,
                weight_grams=position.held_grams if position else None,
                purity=asset.purity,
                movements=[_movement_schema(m) for m in asset.movements],
                fine_weight_grams=fine_grams,
                spot_price_per_gram_base_currency=spot_per_gram_base,
                current_value_base_currency=value_base,
                value_date=today,
                pnl_base_currency=pnl,
                realized_pnl_base_currency=realized,
                created_at=asset.created_at,
            )
        )
    return result


def _movement_schema(movement: PhysicalAssetMovement) -> MetalMovement:
    return MetalMovement(
        id=movement.id,
        type=MetalMovementType(movement.type),
        date=movement.date,
        weight_grams=movement.weight_grams,
        price=movement.price,
        price_base_currency=movement.price_base_currency,
        account_id=_leg_account_id(movement.transaction),
        notes=movement.notes,
    )


def _leg_account_id(leg: Transaction | None) -> UUID | None:
    # A retired leg (an "unsell", a deleted movement, or deleted from the
    # transactions page) no longer says where the money went.
    return leg.account_id if leg is not None and leg.deleted_at is None else None
