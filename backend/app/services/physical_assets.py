"""
Valuation of physical assets: vehicles and precious metals.

Neither has a market quote of its own, so both are estimates — and both are
deliberately conservative:

- A vehicle loses a fixed share of its value per year, compounded daily
  from its anchor: the purchase, or the latest manual valuation on or
  before the date asked about. A valuation re-anchors the curve rather than
  overriding one point, so the estimate keeps sliding after an appraisal
  instead of freezing at it.
- A metal object is worth its fine content (weight × purity) at today's
  spot price. That includes jewellery: craftsmanship and brand have no
  dependable resale market — a "compro oro" pays melt value — so counting
  them would inflate net worth with money nobody would actually pay.

Spot prices are COMEX/NYMEX futures from Yahoo Finance, in USD per troy
ounce, cached through the same `assets`/`asset_prices` rows as portfolio
holdings (the migration seeds one `metal` asset per metal).
"""

from datetime import date as date_
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.orm import Query, Session

from app.models import Asset, PhysicalAsset, Transaction, User
from app.schemas import (
    MetalForm,
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
    # The sale date itself is excluded: on that day the money is already in
    # the account (or in the user's pocket), so counting the object too
    # would double it.
    return asset.purchase_date <= on_date and (asset.sold_at is None or on_date < asset.sold_at)


def vehicle_value(asset: PhysicalAsset, on_date: date_) -> Decimal:
    """Estimated value in `asset.currency` on `on_date` (assumed held then)."""
    anchor_date = asset.purchase_date
    anchor_value = Decimal(str(asset.purchase_price))
    for valuation in asset.valuations:  # ordered by date
        if valuation.date > on_date:
            break
        anchor_date, anchor_value = valuation.date, Decimal(str(valuation.value))

    years = Decimal(max((on_date - anchor_date).days, 0)) / DAYS_PER_YEAR
    retained = (Decimal("1") - Decimal(str(asset.depreciation_rate))) ** years
    return _money(anchor_value * retained)


def fine_weight_grams(asset: PhysicalAsset) -> Decimal:
    return Decimal(str(asset.weight_grams)) * Decimal(str(asset.purity))


def metal_value_usd(asset: PhysicalAsset, spot_per_ounce_usd: Decimal) -> Decimal:
    return fine_weight_grams(asset) * spot_per_ounce_usd / TROY_OUNCE_GRAMS


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
    query = user_physical_assets_query(db, user)
    if not include_sold:
        query = query.filter(PhysicalAsset.sold_at.is_(None))
    assets = query.order_by(PhysicalAsset.purchase_date, PhysicalAsset.created_at).all()
    return value_physical_assets(db, user, assets)


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
        held = is_held_on(asset, today)
        value_base: Decimal | None = None
        fine_grams: Decimal | None = None
        spot_per_gram_base: Decimal | None = None

        if asset.kind == "vehicle":
            rate = rate_to_base(asset.currency)
            if held and rate is not None:
                value_base = _money(vehicle_value(asset, today) * rate)
        else:
            fine_grams = fine_weight_grams(asset)
            # Never None for a metal (DB CHECK); the guard is for the type checker.
            spot = spot_per_ounce(asset.metal) if asset.metal else None
            usd_rate = rate_to_base(METAL_QUOTE_CURRENCY)
            if spot is not None and usd_rate is not None:
                spot_per_gram_base = _money(spot / TROY_OUNCE_GRAMS * usd_rate)
                if held:
                    value_base = _money(metal_value_usd(asset, spot) * usd_rate)

        cost = asset.purchase_price_base_currency
        realized_or_current = asset.sale_price_base_currency if asset.sold_at else value_base
        pnl = (
            _money(Decimal(str(realized_or_current)) - Decimal(str(cost)))
            if cost is not None and realized_or_current is not None
            else None
        )

        result.append(
            PhysicalAssetWithValue(
                id=asset.id,
                kind=PhysicalAssetKind(asset.kind),
                name=asset.name,
                notes=asset.notes,
                currency=asset.currency,
                purchase_date=asset.purchase_date,
                purchase_price=asset.purchase_price,
                purchase_price_base_currency=asset.purchase_price_base_currency,
                purchase_account_id=_leg_account_id(asset.purchase_transaction),
                sold_at=asset.sold_at,
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
                weight_grams=asset.weight_grams,
                purity=asset.purity,
                fine_weight_grams=fine_grams,
                spot_price_per_gram_base_currency=spot_per_gram_base,
                current_value_base_currency=value_base,
                value_date=today,
                pnl_base_currency=pnl,
                created_at=asset.created_at,
            )
        )
    return result


def _leg_account_id(leg: Transaction | None) -> UUID | None:
    # A leg retired by an "unsell" (or deleted from the transactions page)
    # no longer says where the money went.
    return leg.account_id if leg is not None and leg.deleted_at is None else None
