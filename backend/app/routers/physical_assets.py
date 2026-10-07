"""
Physical assets: vehicles and precious metals, valued in
`services/physical_assets.py` and counted in net worth (never in cash).

Paying for one or selling one can optionally move money on an account. That
movement is a one-sided `transfer` (`services/transfers.py:create_cash_leg`),
kept in sync with the asset the same way a portfolio buy/sell keeps its
cash leg: the asset owns it, and editing the purchase edits the leg.

A vehicle is bought and sold whole (`/sell`, `/unsell`). A metal position is
bought into and sold from by the gram (`/movements`); creating one records
its first buy.
"""

from datetime import UTC, datetime
from datetime import date as date_
from decimal import Decimal
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import (
    Account,
    Currency,
    PhysicalAsset,
    PhysicalAssetMovement,
    PhysicalAssetValuation,
    Transaction,
    User,
)
from app.schemas import (
    MetalMovementCreate,
    MetalMovementType,
    PhysicalAssetCreate,
    PhysicalAssetKind,
    PhysicalAssetSell,
    PhysicalAssetUpdate,
    PhysicalAssetValuationCreate,
    PhysicalAssetWithValue,
)
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate
from app.services.ownership import get_owned_account, get_owned_leaf_category
from app.services.physical_assets import (
    OversoldError,
    metal_position,
    physical_assets_with_value,
    value_physical_assets,
)
from app.services.transfers import create_cash_leg

router = APIRouter(prefix="/api/v1/physical-assets", tags=["physical-assets"])

_VEHICLE_FIELDS = ("vehicle_type", "depreciation_rate")
_METAL_FIELDS = ("metal", "metal_form", "weight_grams", "purity")
# Required on create; on update they may be omitted but never cleared.
_REQUIRED_FIELDS = {
    PhysicalAssetKind.vehicle.value: (*_VEHICLE_FIELDS, "purchase_price"),
    PhysicalAssetKind.metal.value: _METAL_FIELDS,
}
_FOREIGN_FIELDS = {
    PhysicalAssetKind.vehicle.value: _METAL_FIELDS,
    PhysicalAssetKind.metal.value: _VEHICLE_FIELDS,
}
# A metal's purchase lives in its movements: on create the purchase_* fields
# describe the first buy, but a later edit goes through the movements.
_METAL_MOVEMENT_FIELDS = ("purchase_date", "purchase_price")


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _check_kind_fields(kind: str, data: dict, *, creating: bool) -> None:
    foreign = [f for f in _FOREIGN_FIELDS[kind] if data.get(f) is not None]
    if not creating and kind == PhysicalAssetKind.metal.value:
        moved = [f for f in _METAL_MOVEMENT_FIELDS if f in data]
        if moved:
            raise _unprocessable(
                f"Edit a metal's {', '.join(moved)} through its movements instead"
            )
    if foreign:
        raise _unprocessable(f"Fields not applicable to a {kind}: {', '.join(foreign)}")
    required = _REQUIRED_FIELDS[kind]
    if creating:
        missing = [f for f in required if data.get(f) is None]
    else:
        missing = [f for f in required if f in data and data[f] is None]
    if missing:
        raise _unprocessable(f"Fields required for a {kind}: {', '.join(missing)}")


def _get_owned_physical_asset(db: Session, asset_id: UUID, user: User) -> PhysicalAsset:
    asset = (
        db.query(PhysicalAsset)
        .filter(
            PhysicalAsset.id == asset_id,
            PhysicalAsset.user_id == user.id,
            PhysicalAsset.deleted_at.is_(None),
        )
        .first()
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Physical asset not found"
        )
    return asset


def _rate(db: Session, currency: str, user: User, on_date: date_) -> Decimal:
    try:
        return get_rate(db, currency, user.base_currency, on_date)
    except ExchangeRateUnavailable as exc:
        raise _unprocessable(str(exc)) from exc


def _cash_account(
    db: Session,
    user: User,
    account_id: UUID | None,
    category_id: UUID | None,
    currency: str,
) -> tuple[Account | None, UUID | None]:
    """The optional account a purchase is paid from / a sale paid into."""
    if account_id is None:
        if category_id is not None:
            raise _unprocessable("A category only applies to a movement on an account")
        return None, None
    account = get_owned_account(db, account_id, user)
    # Converting here would mean a rate lookup inside a multi-row write,
    # and the leg's amount would no longer match the price the user typed.
    if account.currency != currency:
        raise _unprocessable("The account must be in the asset's currency")
    category = (
        get_owned_leaf_category(db, category_id, user, "transfer").id if category_id else None
    )
    return account, category


def _retire_leg(db: Session, transaction_id: UUID | None) -> None:
    if transaction_id is None:
        return
    leg = db.get(Transaction, transaction_id)
    if leg is not None and leg.deleted_at is None:
        leg.deleted_at = datetime.now(UTC)


def _require_vehicle(asset: PhysicalAsset, detail: str) -> None:
    if asset.kind != PhysicalAssetKind.vehicle.value:
        raise _unprocessable(detail)


def _check_ledger(movements: list) -> None:
    """Refuse a write that would make the position sell grams it never held."""
    try:
        metal_position(movements)
    except OversoldError as exc:
        raise _unprocessable(str(exc)) from exc


def _valued(db: Session, user: User, asset: PhysicalAsset) -> PhysicalAssetWithValue:
    db.refresh(asset)  # reloads the valuations relationship after a write
    valued = value_physical_assets(db, user, [asset])[0]
    db.commit()  # persist any price/rate cache rows filled in while valuing
    return valued


@router.get("", response_model=list[PhysicalAssetWithValue])
def list_physical_assets(
    include_sold: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PhysicalAssetWithValue]:
    assets = physical_assets_with_value(db, current_user, include_sold=include_sold)
    db.commit()  # persist the price/rate cache rows filled in above
    return assets


@router.post("", response_model=PhysicalAssetWithValue, status_code=status.HTTP_201_CREATED)
def create_physical_asset(
    payload: PhysicalAssetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PhysicalAssetWithValue:
    data = payload.model_dump()
    _check_kind_fields(payload.kind.value, data, creating=True)
    if db.get(Currency, payload.currency) is None:
        raise _unprocessable(f"Unsupported currency {payload.currency!r}")

    if payload.account_id is not None and payload.purchase_price is None:
        raise _unprocessable("A purchase paid from an account needs a purchase price")
    account, category_id = _cash_account(
        db, current_user, payload.account_id, payload.category_id, payload.currency
    )

    # Resolved before the first db.add(): a cache miss must not land between
    # the leg and the asset.
    rate = (
        _rate(db, payload.currency, current_user, payload.purchase_date)
        if payload.purchase_price is not None
        else None
    )
    price_base = (
        payload.purchase_price * rate
        if payload.purchase_price is not None and rate is not None
        else None
    )

    leg = None
    if account is not None and rate is not None and payload.purchase_price is not None:
        leg = create_cash_leg(
            db,
            account=account,
            amount=-payload.purchase_price,
            currency=payload.currency,
            rate=rate,
            on_date=payload.purchase_date,
            description=f"Acquisto {payload.name}",
            category_id=category_id,
        )

    is_vehicle = payload.kind == PhysicalAssetKind.vehicle
    asset = PhysicalAsset(
        user_id=current_user.id,
        kind=payload.kind.value,
        name=payload.name,
        notes=payload.notes,
        currency=payload.currency,
        purchase_date=payload.purchase_date if is_vehicle else None,
        purchase_price=payload.purchase_price if is_vehicle else None,
        purchase_price_base_currency=price_base if is_vehicle else None,
        purchase_transaction_id=leg.id if leg and is_vehicle else None,
        vehicle_type=payload.vehicle_type.value if payload.vehicle_type else None,
        depreciation_rate=payload.depreciation_rate,
        metal=payload.metal.value if payload.metal else None,
        metal_form=payload.metal_form.value if payload.metal_form else None,
        purity=payload.purity,
    )
    db.add(asset)
    if not is_vehicle:
        db.flush()  # populates asset.id for the movement FK
        db.add(
            PhysicalAssetMovement(
                physical_asset_id=asset.id,
                type=MetalMovementType.buy.value,
                date=payload.purchase_date,
                weight_grams=payload.weight_grams,
                price=payload.purchase_price,
                price_base_currency=price_base,
                transaction_id=leg.id if leg else None,
            )
        )
    db.commit()
    return _valued(db, current_user, asset)


@router.patch("/{asset_id}", response_model=PhysicalAssetWithValue)
def update_physical_asset(
    asset_id: UUID,
    payload: PhysicalAssetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PhysicalAssetWithValue:
    asset = _get_owned_physical_asset(db, asset_id, current_user)
    update_data = payload.model_dump(exclude_unset=True)
    _check_kind_fields(asset.kind, update_data, creating=False)
    for field in ("name", "purchase_date"):
        if field in update_data and update_data[field] is None:
            raise _unprocessable(f"{field} cannot be cleared")

    new_date = update_data.get("purchase_date", asset.purchase_date)
    new_price = update_data.get("purchase_price", asset.purchase_price)
    if new_date is not None and asset.sold_at is not None and new_date > asset.sold_at:
        raise _unprocessable("The purchase date cannot be after the sale date")
    first_valuation = asset.valuations[0].date if asset.valuations else None
    if first_valuation is not None and new_date is not None and new_date > first_valuation:
        raise _unprocessable("The purchase date cannot be after an existing valuation")
    if asset.purchase_transaction_id is not None and new_price is None:
        raise _unprocessable("A purchase paid from an account needs a purchase price")

    # Frozen-rate rule: only a change to the price or its date reconverts.
    reprice = "purchase_price" in update_data or "purchase_date" in update_data
    rate = (
        _rate(db, asset.currency, current_user, new_date)
        if reprice and new_price is not None and new_date is not None
        else None
    )

    for field, value in update_data.items():
        setattr(asset, field, value.value if isinstance(value, Enum) else value)

    if reprice:
        asset.purchase_price_base_currency = (
            new_price * rate if new_price is not None and rate is not None else None
        )
        leg = (
            db.get(Transaction, asset.purchase_transaction_id)
            if asset.purchase_transaction_id
            else None
        )
        if leg is not None and new_price is not None and rate is not None and new_date:
            leg.amount = -new_price
            leg.amount_base_currency = -new_price * rate
            leg.exchange_rate = rate
            leg.date = new_date

    db.commit()
    return _valued(db, current_user, asset)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_physical_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    asset = _get_owned_physical_asset(db, asset_id, current_user)
    now = datetime.now(UTC)
    asset.deleted_at = now
    for valuation in asset.valuations:
        valuation.deleted_at = now
    # Deleting the object deletes its history, cash included — same as
    # deleting a portfolio buy. Selling is how you keep the money trail.
    _retire_leg(db, asset.purchase_transaction_id)
    _retire_leg(db, asset.sale_transaction_id)
    for movement in asset.movements:
        movement.deleted_at = now
        _retire_leg(db, movement.transaction_id)
    db.commit()


@router.post("/{asset_id}/sell", response_model=PhysicalAssetWithValue)
def sell_physical_asset(
    asset_id: UUID,
    payload: PhysicalAssetSell,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PhysicalAssetWithValue:
    asset = _get_owned_physical_asset(db, asset_id, current_user)
    _require_vehicle(asset, "A metal is sold by the gram through its movements")
    if asset.sold_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already sold")
    assert asset.purchase_date is not None  # a vehicle always has one (DB CHECK)
    if payload.sold_at < asset.purchase_date:
        raise _unprocessable("The sale date cannot be before the purchase date")
    last_valuation = asset.valuations[-1].date if asset.valuations else None
    if last_valuation is not None and payload.sold_at <= last_valuation:
        raise _unprocessable("The sale date must be after the latest valuation")

    account, category_id = _cash_account(
        db, current_user, payload.account_id, payload.category_id, asset.currency
    )
    rate = _rate(db, asset.currency, current_user, payload.sold_at)

    leg = None
    if account is not None:
        leg = create_cash_leg(
            db,
            account=account,
            amount=payload.sale_price,
            currency=asset.currency,
            rate=rate,
            on_date=payload.sold_at,
            description=f"Vendita {asset.name}",
            category_id=category_id,
        )

    asset.sold_at = payload.sold_at
    asset.sale_price = payload.sale_price
    asset.sale_price_base_currency = payload.sale_price * rate
    asset.sale_transaction_id = leg.id if leg else None
    db.commit()
    return _valued(db, current_user, asset)


@router.post("/{asset_id}/unsell", response_model=PhysicalAssetWithValue)
def unsell_physical_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PhysicalAssetWithValue:
    asset = _get_owned_physical_asset(db, asset_id, current_user)
    _require_vehicle(asset, "Delete the metal's sell movement instead")
    if asset.sold_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not sold")
    _retire_leg(db, asset.sale_transaction_id)
    asset.sold_at = None
    asset.sale_price = None
    asset.sale_price_base_currency = None
    asset.sale_transaction_id = None
    db.commit()
    return _valued(db, current_user, asset)


@router.post(
    "/{asset_id}/valuations",
    response_model=PhysicalAssetWithValue,
    status_code=status.HTTP_201_CREATED,
)
def create_valuation(
    asset_id: UUID,
    payload: PhysicalAssetValuationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PhysicalAssetWithValue:
    asset = _get_owned_physical_asset(db, asset_id, current_user)
    # A metal's value is its spot price; an appraisal would have nothing to
    # re-anchor, and silently ignoring it would be worse than refusing.
    _require_vehicle(asset, "Only vehicles take manual valuations")
    assert asset.purchase_date is not None  # a vehicle always has one (DB CHECK)
    if payload.date < asset.purchase_date:
        raise _unprocessable("A valuation cannot predate the purchase")
    if asset.sold_at is not None and payload.date >= asset.sold_at:
        raise _unprocessable("A valuation must predate the sale")
    if any(v.date == payload.date for v in asset.valuations):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This vehicle already has a valuation on that date",
        )

    db.add(
        PhysicalAssetValuation(
            physical_asset_id=asset.id,
            date=payload.date,
            value=payload.value,
            notes=payload.notes,
        )
    )
    db.commit()
    return _valued(db, current_user, asset)


@router.delete("/{asset_id}/valuations/{valuation_id}", response_model=PhysicalAssetWithValue)
def delete_valuation(
    asset_id: UUID,
    valuation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PhysicalAssetWithValue:
    asset = _get_owned_physical_asset(db, asset_id, current_user)
    valuation = next((v for v in asset.valuations if v.id == valuation_id), None)
    if valuation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Valuation not found")
    valuation.deleted_at = datetime.now(UTC)
    db.commit()
    return _valued(db, current_user, asset)


@router.post(
    "/{asset_id}/movements",
    response_model=PhysicalAssetWithValue,
    status_code=status.HTTP_201_CREATED,
)
def create_movement(
    asset_id: UUID,
    payload: MetalMovementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PhysicalAssetWithValue:
    asset = _get_owned_physical_asset(db, asset_id, current_user)
    if asset.kind != PhysicalAssetKind.metal.value:
        raise _unprocessable("Only a metal position is bought and sold by the gram")
    is_sale = payload.type == MetalMovementType.sell
    if is_sale and payload.price is None:
        raise _unprocessable("A sale needs a price")
    if payload.account_id is not None and payload.price is None:
        raise _unprocessable("A purchase paid from an account needs a price")

    movement = PhysicalAssetMovement(
        physical_asset_id=asset.id,
        type=payload.type.value,
        date=payload.date,
        weight_grams=payload.weight_grams,
        price=payload.price,
        notes=payload.notes,
    )
    _check_ledger([*asset.movements, movement])

    account, category_id = _cash_account(
        db, current_user, payload.account_id, payload.category_id, asset.currency
    )
    # Resolved before the first db.add(), as on create.
    rate = (
        _rate(db, asset.currency, current_user, payload.date)
        if payload.price is not None
        else None
    )
    if payload.price is not None and rate is not None:
        movement.price_base_currency = payload.price * rate
        if account is not None:
            grams = f"{payload.weight_grams.normalize():f}".replace(".", ",")
            verb = "Vendita" if is_sale else "Acquisto"
            leg = create_cash_leg(
                db,
                account=account,
                amount=payload.price if is_sale else -payload.price,
                currency=asset.currency,
                rate=rate,
                on_date=payload.date,
                description=f"{verb} {grams} g {asset.name}",
                category_id=category_id,
            )
            movement.transaction_id = leg.id

    db.add(movement)
    db.commit()
    return _valued(db, current_user, asset)


@router.delete(
    "/{asset_id}/movements/{movement_id}", response_model=PhysicalAssetWithValue
)
def delete_movement(
    asset_id: UUID,
    movement_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PhysicalAssetWithValue:
    asset = _get_owned_physical_asset(db, asset_id, current_user)
    movement = next((m for m in asset.movements if m.id == movement_id), None)
    if movement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movement not found")
    remaining = [m for m in asset.movements if m.id != movement_id]
    # A position with no movements has no date to sit on in the history, and
    # nothing to show: that's a deleted asset, so say so.
    if not remaining:
        raise _unprocessable("This is the only movement — delete the asset instead")
    # Removing a buy can leave a later sale selling grams that were never held.
    _check_ledger(remaining)

    movement.deleted_at = datetime.now(UTC)
    _retire_leg(db, movement.transaction_id)
    db.commit()
    return _valued(db, current_user, asset)
