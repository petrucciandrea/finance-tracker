"""
Vehicle deadlines: insurance, road tax, inspection, service. Reminders, not
movements — completing one writes nothing to the ledger; the expense is an
ordinary transaction. With an amount and an account, an open deadline is a
commitment on that account (see `services/alerts.py`).
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import PhysicalAsset, User, VehicleDeadline
from app.schemas import VehicleDeadline as VehicleDeadlineSchema
from app.schemas import (
    VehicleDeadlineComplete,
    VehicleDeadlineCreate,
    VehicleDeadlineKind,
    VehicleDeadlineUpdate,
)
from app.services.ownership import get_owned_account

router = APIRouter(prefix="/api/v1/vehicle-deadlines", tags=["vehicle-deadlines"])


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _get_owned_vehicle(db: Session, asset_id: UUID, user: User) -> PhysicalAsset:
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if asset.kind != "vehicle":
        raise _unprocessable("Deadlines are for vehicles")
    return asset


def _get_owned_deadline(db: Session, deadline_id: UUID, user: User) -> VehicleDeadline:
    deadline = (
        db.query(VehicleDeadline)
        .filter(
            VehicleDeadline.id == deadline_id,
            VehicleDeadline.user_id == user.id,
            VehicleDeadline.deleted_at.is_(None),
        )
        .first()
    )
    if deadline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found")
    return deadline


def _check(kind: str, label: str | None, amount, account_id) -> None:
    if kind == VehicleDeadlineKind.other.value and not label:
        raise _unprocessable("Name the deadline")
    if account_id is not None and amount is None:
        raise _unprocessable("A deadline paid from an account needs an amount")


@router.get("", response_model=list[VehicleDeadlineSchema])
def list_deadlines(
    include_done: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[VehicleDeadline]:
    query = (
        db.query(VehicleDeadline)
        .join(PhysicalAsset, PhysicalAsset.id == VehicleDeadline.physical_asset_id)
        .filter(
            VehicleDeadline.user_id == current_user.id,
            VehicleDeadline.deleted_at.is_(None),
            PhysicalAsset.deleted_at.is_(None),
        )
    )
    if not include_done:
        query = query.filter(VehicleDeadline.done_on.is_(None))
    return query.order_by(VehicleDeadline.due_date, VehicleDeadline.created_at).all()


@router.post("", response_model=VehicleDeadlineSchema, status_code=status.HTTP_201_CREATED)
def create_deadline(
    payload: VehicleDeadlineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VehicleDeadline:
    vehicle = _get_owned_vehicle(db, payload.physical_asset_id, current_user)
    if vehicle.sold_at is not None:
        raise _unprocessable("The vehicle was sold")
    account = (
        get_owned_account(db, payload.account_id, current_user)
        if payload.account_id is not None
        else None
    )
    _check(payload.kind.value, payload.label, payload.amount, payload.account_id)
    deadline = VehicleDeadline(
        user_id=current_user.id,
        physical_asset_id=vehicle.id,
        kind=payload.kind.value,
        label=payload.label,
        due_date=payload.due_date,
        amount=payload.amount,
        currency=account.currency if account is not None else vehicle.currency,
        account_id=account.id if account is not None else None,
        notes=payload.notes,
    )
    db.add(deadline)
    db.commit()
    db.refresh(deadline)
    return deadline


@router.patch("/{deadline_id}", response_model=VehicleDeadlineSchema)
def update_deadline(
    deadline_id: UUID,
    payload: VehicleDeadlineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VehicleDeadline:
    deadline = _get_owned_deadline(db, deadline_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    for field in ("kind", "due_date"):
        if field in data and data[field] is None:
            raise _unprocessable(f"{field} can't be cleared")
    if "kind" in data:
        data["kind"] = data["kind"].value
    if data.get("account_id") is not None:
        account = get_owned_account(db, data["account_id"], current_user)
        # The amount is typed in the account's currency.
        data["currency"] = account.currency
    elif "account_id" in data:
        data["currency"] = deadline_vehicle_currency(db, deadline)
    _check(
        data.get("kind", deadline.kind),
        data.get("label", deadline.label),
        data.get("amount", deadline.amount),
        data.get("account_id", deadline.account_id),
    )
    for field, value in data.items():
        setattr(deadline, field, value)
    db.commit()
    db.refresh(deadline)
    return deadline


def deadline_vehicle_currency(db: Session, deadline: VehicleDeadline) -> str:
    vehicle = db.get(PhysicalAsset, deadline.physical_asset_id)
    assert vehicle is not None
    return vehicle.currency


@router.post("/{deadline_id}/complete", response_model=list[VehicleDeadlineSchema])
def complete_deadline(
    deadline_id: UUID,
    payload: VehicleDeadlineComplete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[VehicleDeadline]:
    """Done; with `next_due_date`, the next occurrence is created too. Returns both."""
    deadline = _get_owned_deadline(db, deadline_id, current_user)
    if deadline.done_on is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already done")
    if payload.next_due_date is not None and payload.next_due_date <= deadline.due_date:
        raise _unprocessable("The next deadline must come after this one")
    deadline.done_on = payload.done_on
    rows = [deadline]
    if payload.next_due_date is not None:
        following = VehicleDeadline(
            user_id=current_user.id,
            physical_asset_id=deadline.physical_asset_id,
            kind=deadline.kind,
            label=deadline.label,
            due_date=payload.next_due_date,
            amount=deadline.amount,
            currency=deadline.currency,
            account_id=deadline.account_id,
            notes=deadline.notes,
        )
        db.add(following)
        rows.append(following)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


@router.post("/{deadline_id}/reopen", response_model=VehicleDeadlineSchema)
def reopen_deadline(
    deadline_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VehicleDeadline:
    deadline = _get_owned_deadline(db, deadline_id, current_user)
    if deadline.done_on is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not done")
    deadline.done_on = None
    db.commit()
    db.refresh(deadline)
    return deadline


@router.delete("/{deadline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deadline(
    deadline_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deadline = _get_owned_deadline(db, deadline_id, current_user)
    deadline.deleted_at = datetime.now(UTC)
    db.commit()
