"""
What the portfolio is made of: the allocation by asset class, region,
sector and currency, and the per-product weights behind it.

Weights are edited per product and per dimension, the whole dimension at
once. A product the user never touched reads from the reference file or
from what its type implies; deleting a dimension's weights goes back to
that.
"""

from datetime import date as date_
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Account, Asset, AssetExposure, AssetProfile, AssetTransaction, User
from app.schemas import Asset as AssetSchema
from app.schemas import (
    AssetExposures,
    AssetExposureUpdate,
    ExposureDimension,
    ExposureSuggestion,
    PortfolioAllocation,
)
from app.services import asset_profiles
from app.services import portfolio_allocation as service

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


def _get_owned_asset(db: Session, asset_id: UUID, user: User) -> Asset:
    """
    An asset the user has traded. `assets` is shared, so ownership here
    means "appears in one of the user's buy/sell rows" — weights for a
    product nobody in this account holds would be noise in their export.
    """
    asset = (
        db.query(Asset)
        .join(AssetTransaction, AssetTransaction.asset_id == Asset.id)
        .join(Account, Account.id == AssetTransaction.account_id)
        .filter(
            Asset.id == asset_id,
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
            AssetTransaction.deleted_at.is_(None),
        )
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.get("/allocation", response_model=PortfolioAllocation)
def get_allocation(
    dimension: ExposureDimension = ExposureDimension.asset_class,
    include_cash: Annotated[bool, Query()] = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioAllocation:
    # Fetch today's quotes first, then value from the caches like the
    # alerts do: one valuation path, and a read that writes, so commit.
    service.warm_caches(db, current_user)
    result = service.allocation(
        db, current_user, dimension, date_.today(), include_cash=include_cash
    )
    db.commit()
    return result


@router.get("/assets/{asset_id}/exposures", response_model=AssetExposures)
def get_exposures(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetExposures:
    asset = _get_owned_asset(db, asset_id, current_user)
    resolved = service.resolve_exposures(db, current_user, [asset])[asset.id]
    return AssetExposures(
        asset=AssetSchema.model_validate(asset),
        dimensions=[service.to_dimension_schema(d, r) for d, r in resolved.items()],
    )


@router.put("/assets/{asset_id}/exposures/{dimension}", response_model=AssetExposures)
def put_exposures(
    asset_id: UUID,
    dimension: ExposureDimension,
    payload: AssetExposureUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetExposures:
    asset = _get_owned_asset(db, asset_id, current_user)
    if not payload.weights:
        # No rows would read as "untouched" and bring the reference back, so
        # an empty set can't mean "none of this". DELETE is the reset.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Send at least one weight, or DELETE to go back to the reference",
        )
    problem = service.validate_weights(dimension, payload.weights)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=problem)

    db.query(AssetExposure).filter(
        AssetExposure.user_id == current_user.id,
        AssetExposure.asset_id == asset.id,
        AssetExposure.dimension == dimension.value,
    ).delete(synchronize_session=False)
    for w in payload.weights:
        db.add(
            AssetExposure(
                user_id=current_user.id,
                asset_id=asset.id,
                dimension=dimension.value,
                bucket=w.bucket,
                weight=w.weight,
            )
        )
    profile = (
        db.query(AssetProfile)
        .filter(AssetProfile.user_id == current_user.id, AssetProfile.asset_id == asset.id)
        .first()
    )
    if profile is None:
        profile = AssetProfile(user_id=current_user.id, asset_id=asset.id)
        db.add(profile)
    profile.as_of = payload.as_of or date_.today()
    if payload.notes is not None:
        profile.notes = payload.notes
    db.commit()
    return get_exposures(asset.id, db, current_user)


@router.delete("/assets/{asset_id}/exposures/{dimension}", response_model=AssetExposures)
def delete_exposures(
    asset_id: UUID,
    dimension: ExposureDimension,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetExposures:
    asset = _get_owned_asset(db, asset_id, current_user)
    db.query(AssetExposure).filter(
        AssetExposure.user_id == current_user.id,
        AssetExposure.asset_id == asset.id,
        AssetExposure.dimension == dimension.value,
    ).delete(synchronize_session=False)
    db.commit()
    return get_exposures(asset.id, db, current_user)


@router.get("/assets/{asset_id}/exposure-suggestion", response_model=ExposureSuggestion)
def exposure_suggestion(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExposureSuggestion:
    """Pre-fills the editor for a single stock; writes nothing."""
    asset = _get_owned_asset(db, asset_id, current_user)
    try:
        return asset_profiles.suggest(asset)
    except asset_profiles.AssetProfileUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No suggestion available for this product — fill it in by hand",
        ) from exc
