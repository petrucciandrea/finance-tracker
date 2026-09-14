"""
Savings goals: the rungs of the waterfall, their funding accounts, and the
computed cascade.

Kept apart from `planning.py` — that file answers "how is this month
going", this one owns a resource with its own CRUD plus the engine that
walks it. The two share `/api/v1/planning` as a prefix because they are
one feature to a client.
"""

from datetime import UTC, datetime
from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from app.deps import get_current_user, get_db
from app.models import SavingsGoal, SavingsGoalSource, User
from app.schemas import (
    SavingsGoal as SavingsGoalSchema,
)
from app.schemas import (
    SavingsGoalCreate,
    SavingsGoalSourceCreate,
    SavingsGoalUpdate,
    TargetMode,
    WaterfallPlan,
)
from app.schemas import (
    SavingsGoalSource as SavingsGoalSourceSchema,
)
from app.services import waterfall as waterfall_service
from app.services.ownership import get_owned_account

router = APIRouter(prefix="/api/v1/planning", tags=["planning"])


def _get_owned_goal(db: Session, goal_id: UUID, user: User) -> SavingsGoal:
    goal = (
        db.query(SavingsGoal)
        .options(selectinload(SavingsGoal.sources))
        .filter(
            SavingsGoal.id == goal_id,
            SavingsGoal.user_id == user.id,
            SavingsGoal.deleted_at.is_(None),
        )
        .first()
    )
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings goal not found")
    return goal


def _validate_target(
    target_mode: str, target_months: Decimal | None, target_amount: Decimal | None
) -> None:
    """
    Each mode takes exactly the parameter it needs. The database enforces
    this too, but a CheckConstraint violation would surface as a generic
    500 — here it becomes a 422 naming the missing or surplus field.
    """
    if target_mode == TargetMode.months_of_primary_expenses.value:
        if target_months is None or target_amount is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A months_of_primary_expenses goal needs target_months and no target_amount",
            )
    elif target_mode == TargetMode.fixed_amount.value:
        if target_amount is None or target_months is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A fixed_amount goal needs target_amount and no target_months",
            )
    elif target_months is not None or target_amount is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An open_ended goal takes neither target_months nor target_amount",
        )


def _reject_second_open_ended(db: Session, user: User, exclude_goal_id: UUID | None = None) -> None:
    """
    Only one open-ended rung. It absorbs the whole remainder and closes the
    cascade, so a second one could never receive anything no matter how the
    priorities are arranged — better a 409 than a goal that silently sits
    at zero forever.
    """
    query = db.query(SavingsGoal).filter(
        SavingsGoal.user_id == user.id,
        SavingsGoal.deleted_at.is_(None),
        SavingsGoal.target_mode == TargetMode.open_ended.value,
    )
    if exclude_goal_id is not None:
        query = query.filter(SavingsGoal.id != exclude_goal_id)

    if query.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An open-ended goal already exists — it already absorbs the remainder",
        )


@router.get("/goals", response_model=list[SavingsGoalSchema])
def list_goals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SavingsGoal]:
    return waterfall_service.list_goals(db, current_user)


@router.post("/goals", response_model=SavingsGoalSchema, status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: SavingsGoalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavingsGoal:
    _validate_target(payload.target_mode.value, payload.target_months, payload.target_amount)
    if payload.target_mode == TargetMode.open_ended:
        _reject_second_open_ended(db, current_user)

    goal = SavingsGoal(
        user_id=current_user.id,
        name=payload.name,
        kind=payload.kind.value,
        priority=payload.priority,
        target_mode=payload.target_mode.value,
        target_months=payload.target_months,
        target_amount=payload.target_amount,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.get("/waterfall", response_model=WaterfallPlan)
def waterfall(
    on_date: date_ = Query(default_factory=date_.today, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WaterfallPlan:
    # Read-only: it computes suggestions but writes nothing. Executing them
    # is phase D's separate, explicit endpoint.
    return waterfall_service.compute_waterfall(db, current_user, on_date)


@router.get("/goals/{goal_id}", response_model=SavingsGoalSchema)
def get_goal(
    goal_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavingsGoal:
    return _get_owned_goal(db, goal_id, current_user)


@router.patch("/goals/{goal_id}", response_model=SavingsGoalSchema)
def update_goal(
    goal_id: UUID,
    payload: SavingsGoalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavingsGoal:
    goal = _get_owned_goal(db, goal_id, current_user)
    update_data = payload.model_dump(exclude_unset=True)

    # Validate the resulting row, not the patch: switching target_mode also
    # changes which parameter is required, and the two may arrive together.
    target_mode = update_data.get("target_mode", TargetMode(goal.target_mode))
    target_mode_value = getattr(target_mode, "value", target_mode)
    _validate_target(
        target_mode_value,
        update_data.get("target_months", goal.target_months),
        update_data.get("target_amount", goal.target_amount),
    )
    if target_mode_value == TargetMode.open_ended.value:
        _reject_second_open_ended(db, current_user, exclude_goal_id=goal.id)

    for field, value in update_data.items():
        setattr(goal, field, getattr(value, "value", value))

    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(
    goal_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    goal = _get_owned_goal(db, goal_id, current_user)
    goal.deleted_at = datetime.now(UTC)
    # The mappings go with it, freeing those accounts for another goal.
    for source in goal.sources:
        if source.deleted_at is None:
            source.deleted_at = datetime.now(UTC)
    db.commit()


@router.post(
    "/goals/{goal_id}/sources",
    response_model=SavingsGoalSourceSchema,
    status_code=status.HTTP_201_CREATED,
)
def add_source(
    goal_id: UUID,
    payload: SavingsGoalSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavingsGoalSource:
    goal = _get_owned_goal(db, goal_id, current_user)
    get_owned_account(db, payload.account_id, current_user)

    # An account may fund at most one goal, or its balance would count
    # toward both and the cascade would think it had twice the money.
    # Scoped to the user, so it can't be a unique index on this table.
    existing = (
        db.query(SavingsGoalSource)
        .join(SavingsGoal, SavingsGoal.id == SavingsGoalSource.goal_id)
        .filter(
            SavingsGoal.user_id == current_user.id,
            SavingsGoal.deleted_at.is_(None),
            SavingsGoalSource.account_id == payload.account_id,
            SavingsGoalSource.deleted_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account already funds another savings goal",
        )

    source = SavingsGoalSource(goal_id=goal.id, account_id=payload.account_id)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/goals/{goal_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_source(
    goal_id: UUID,
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    goal = _get_owned_goal(db, goal_id, current_user)
    source = next(
        (s for s in goal.sources if s.id == source_id and s.deleted_at is None), None
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    source.deleted_at = datetime.now(UTC)
    db.commit()
