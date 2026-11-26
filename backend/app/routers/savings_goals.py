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
from app.models import (
    Asset,
    FlatRateProvisionSource,
    SavingsAllocation,
    SavingsGoal,
    SavingsGoalSource,
    Transaction,
    User,
)
from app.schemas import (
    SavingsAllocation as SavingsAllocationSchema,
)
from app.schemas import (
    SavingsGoal as SavingsGoalSchema,
)
from app.schemas import (
    SavingsGoalCreate,
    SavingsGoalKind,
    SavingsGoalSourceCreate,
    SavingsGoalUpdate,
    TargetMode,
    WaterfallExecuteRequest,
    WaterfallExecuteResponse,
    WaterfallPlan,
)
from app.schemas import (
    SavingsGoalSource as SavingsGoalSourceSchema,
)
from app.schemas import (
    Transaction as TransactionSchema,
)
from app.services import flat_rate as flat_rate_service
from app.services import waterfall as waterfall_service
from app.services.net_worth import compute_holding_positions
from app.services.ownership import get_owned_account
from app.services.periods import period_bounds
from app.services.transfers import create_linked_transfer

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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A months_of_primary_expenses goal needs target_months and no target_amount",
            )
    elif target_mode == TargetMode.fixed_amount.value:
        if target_amount is None or target_months is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A fixed_amount goal needs target_amount and no target_months",
            )
    elif target_months is not None or target_amount is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An open_ended goal takes neither target_months nor target_amount",
        )


def _validate_dates(
    kind: str,
    target_mode: str,
    target_date: date_ | None,
    completed_at: date_ | None,
) -> None:
    """
    A date is a deadline for an amount to be ready by: it needs a fixed
    amount (a dynamic target has no fixed finish line) and belongs to the
    medium term, the pillar of things bought on a date. The emergency fund
    is never "due", and the long term is open by nature. The database has
    the same rule as a CHECK; this makes it a 422.
    """
    if target_date is not None and (
        kind != SavingsGoalKind.medium_term.value or target_mode != TargetMode.fixed_amount.value
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only a medium-term goal with a fixed amount can have a target date",
        )
    if completed_at is not None:
        if target_mode != TargetMode.fixed_amount.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only a goal with a fixed amount can be marked as reached",
            )
        if completed_at > date_.today():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A goal can't be reached in the future",
            )


def _placement_priority(
    db: Session, user: User, kind: str, target_date: date_ | None
) -> int:
    """
    Where a goal created without a priority goes, inside its own pillar (the
    pillar is fixed by `kind`, see `waterfall.PILLAR_RANK`). A dated goal
    goes among the dated ones by date, nearest first, so the car due next
    year comes before the down payment due in five. Anything else goes last
    in its pillar, but above an open-ended goal, which absorbs the rest and
    must stay at the bottom. The user can reorder afterwards: the date only
    decides the starting position.
    """
    goals = [g for g in waterfall_service.list_goals(db, user) if g.completed_at is None]
    same = [g for g in goals if g.kind == kind]
    if target_date is not None:
        later = [g.priority for g in same if g.target_date and g.target_date > target_date]
        if later:
            return min(later)
        dated = [g.priority for g in same if g.target_date]
        if dated:
            return max(dated) + 1
    tail = [g.priority for g in same if g.target_mode == TargetMode.open_ended.value]
    if tail:
        return min(tail)
    return max((g.priority for g in goals), default=-1) + 1


def _make_room(db: Session, user: User, priority: int) -> None:
    """Shift every goal at `priority` or below down by one, to insert above them."""
    for goal in waterfall_service.list_goals(db, user):
        if goal.priority >= priority:
            goal.priority += 1


def _reject_open_ended_outside_investing(kind: str, target_mode: str) -> None:
    """
    An open-ended goal absorbs whatever reaches it, and goals are filled pillar
    by pillar: one in pillar 2 or 3 would starve every pillar after it, with
    no priority able to move it below them. "Whatever is left" is pillar 4's
    job by definition.
    """
    if target_mode == TargetMode.open_ended.value and kind != SavingsGoalKind.long_term.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only a long_term goal can be open-ended",
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
    _validate_dates(payload.kind.value, payload.target_mode.value, payload.target_date, None)
    if payload.target_date is not None and payload.target_date <= date_.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A new goal's target date must be in the future",
        )
    _reject_open_ended_outside_investing(payload.kind.value, payload.target_mode.value)
    if payload.target_mode == TargetMode.open_ended:
        _reject_second_open_ended(db, current_user)

    priority = payload.priority
    if priority is None:
        priority = _placement_priority(db, current_user, payload.kind.value, payload.target_date)
        _make_room(db, current_user, priority)

    goal = SavingsGoal(
        user_id=current_user.id,
        name=payload.name,
        kind=payload.kind.value,
        priority=priority,
        target_mode=payload.target_mode.value,
        target_months=payload.target_months,
        target_amount=payload.target_amount,
        target_date=payload.target_date,
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


@router.post("/waterfall/execute", response_model=WaterfallExecuteResponse)
def execute_waterfall(
    payload: WaterfallExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WaterfallExecuteResponse:
    """
    Materialise selected suggestions as giroconti.

    The only endpoint in the planning engine that writes transactions, and
    it only ever acts on what the user explicitly selected — the cascade is
    never executed as a side effect of recording income.

    Every item is re-validated rather than trusted: ownership of the goal
    and the source account, a destination account still mapped to the goal,
    and (inside `create_linked_transfer`) matching currencies and distinct
    accounts. Everything commits once at the end, so a rejected item leaves
    no half-executed batch behind.
    """
    on_date = payload.date or date_.today()
    period_start, _ = period_bounds("monthly", on_date)

    allocations: list[SavingsAllocation] = []
    created: list[Transaction] = []

    try:
        _build_transfers(db, current_user, payload, on_date, period_start, allocations, created)
    except HTTPException:
        # The batch is all-or-nothing. Without this, a bad item late in the
        # list would leave the earlier giroconti flushed and visible —
        # money moved for a request the user was told had failed. Relying
        # on session teardown to undo them is not a guarantee worth making.
        db.rollback()
        raise

    db.commit()
    for row in [*allocations, *created]:
        db.refresh(row)

    # Validated explicitly rather than handed the ORM rows: both schemas are
    # from_attributes models, so this is what FastAPI would do anyway, and
    # doing it here keeps the return type honest.
    return WaterfallExecuteResponse(
        allocations=[SavingsAllocationSchema.model_validate(a) for a in allocations],
        transactions=[TransactionSchema.model_validate(t) for t in created],
    )


def _build_transfers(
    db: Session,
    current_user: User,
    payload: WaterfallExecuteRequest,
    on_date: date_,
    period_start: date_,
    allocations: list[SavingsAllocation],
    created: list[Transaction],
) -> None:
    provision_accounts = {
        s.account_id
        for s in flat_rate_service.active_sources(db, current_user)
        if s.asset_id is None
    }
    for item in payload.items:
        from_account = get_owned_account(db, item.from_account_id, current_user)
        if item.goal_id is None:
            # The tax provision rung: a plain giroconto into a provision
            # account. Not a savings allocation — it doesn't consume the
            # quota's bookkeeping, and once it lands the rung's gap closes.
            assert item.to_account_id is not None
            if item.to_account_id not in provision_accounts:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="That account doesn't hold the tax provision",
                )
            outgoing, incoming = create_linked_transfer(
                db,
                current_user,
                from_account=from_account,
                to_account=get_owned_account(db, item.to_account_id, current_user),
                amount=item.amount,
                on_date=on_date,
                description="Accantonamento tasse",
            )
            created.extend([outgoing, incoming])
            continue

        goal = _get_owned_goal(db, item.goal_id, current_user)

        destination_id = waterfall_service.destination_account_id(goal)
        if destination_id is None and item.to_account_id is not None:
            # Executing the advice "no account linked": the account chosen in
            # the row becomes the goal's source, with the same rules as
            # linking it by hand, in the same all-or-nothing batch.
            destination_id = _link_source(db, current_user, goal, item.to_account_id).account_id
        elif item.to_account_id is not None and item.to_account_id != destination_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"«{goal.name}» already transfers into another account",
            )
        if destination_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Savings goal «{goal.name}» has no account to transfer into",
            )
        to_account = get_owned_account(db, destination_id, current_user)

        outgoing, incoming = create_linked_transfer(
            db,
            current_user,
            from_account=from_account,
            to_account=to_account,
            amount=item.amount,
            on_date=on_date,
            description=f"Risparmio: {goal.name}",
        )

        allocation = SavingsAllocation(
            user_id=current_user.id,
            goal_id=goal.id,
            # The destination leg: the money arriving is what funds the goal.
            transaction_id=incoming.id,
            period_start=period_start,
            amount_base_currency=abs(incoming.amount_base_currency),
        )
        db.add(allocation)
        allocations.append(allocation)
        created.extend([outgoing, incoming])


@router.get("/waterfall/allocations", response_model=list[SavingsAllocationSchema])
def list_allocations(
    on_date: date_ = Query(default_factory=date_.today, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SavingsAllocation]:
    period_start, _ = period_bounds("monthly", on_date)
    return (
        db.query(SavingsAllocation)
        .filter(
            SavingsAllocation.user_id == current_user.id,
            SavingsAllocation.period_start == period_start,
            SavingsAllocation.deleted_at.is_(None),
        )
        .order_by(SavingsAllocation.created_at)
        .all()
    )


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
    target_date = update_data.get("target_date", goal.target_date)
    if target_mode_value != TargetMode.fixed_amount.value and "target_date" not in update_data:
        # Leaving fixed_amount drops the deadline with it rather than 422ing
        # on a field the client didn't touch.
        target_date = None
        update_data["target_date"] = None
    _validate_dates(
        goal.kind,
        target_mode_value,
        target_date,
        update_data.get("completed_at", goal.completed_at),
    )
    if target_mode_value != goal.target_mode:
        # Only on a change: a goal stored that way before the rule still saves.
        _reject_open_ended_outside_investing(goal.kind, target_mode_value)
    if target_mode_value == TargetMode.open_ended.value:
        _reject_second_open_ended(db, current_user, exclude_goal_id=goal.id)

    completing = goal.completed_at is None and update_data.get("completed_at") is not None
    for field, value in update_data.items():
        setattr(goal, field, getattr(value, "value", value))

    if completing:
        # Reached and spent: the accounts are free for the next goal. Not
        # restored on un-completing — by then they may fund another one.
        now = datetime.now(UTC)
        for source in goal.sources:
            if source.deleted_at is None:
                source.deleted_at = now

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


def _link_source(
    db: Session,
    current_user: User,
    goal: SavingsGoal,
    account_id: UUID,
    asset_id: UUID | None = None,
) -> SavingsGoalSource:
    """
    Map an account's cash, or a holding in it, to a goal: shared by the
    sources endpoint and by executing a suggestion for a goal that had no
    account yet. Flushes, never commits — the caller owns the transaction.
    """
    if goal.completed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"«{goal.name}» was already reached",
        )
    account = get_owned_account(db, account_id, current_user)
    # Closing refuses an account that funds a goal; this is the other door.
    if account.closed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The account «{account.name}» is closed",
        )

    if asset_id is not None:
        if db.get(Asset, asset_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        position = compute_holding_positions(db, current_user).get((account.id, asset_id))
        if position is None or position["quantity"] <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="This account holds no position in that product",
            )

    # A holding funds at most one goal: its value counts whole and can't be
    # moved by giroconto, so there is nothing to split. An account's *cash*
    # may fund several goals — goal_values splits it in cascade order — but
    # not the same goal twice.
    query = (
        db.query(SavingsGoalSource)
        .join(SavingsGoal, SavingsGoal.id == SavingsGoalSource.goal_id)
        .filter(
            SavingsGoal.user_id == current_user.id,
            SavingsGoal.deleted_at.is_(None),
            SavingsGoalSource.account_id == account_id,
            SavingsGoalSource.deleted_at.is_(None),
        )
    )
    if asset_id is not None:
        if query.filter(SavingsGoalSource.asset_id == asset_id).first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This already funds another savings goal",
            )
    elif (
        query.filter(
            SavingsGoalSource.asset_id.is_(None), SavingsGoalSource.goal_id == goal.id
        ).first()
        is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account already funds this goal",
        )

    # Earmarked for taxes: the same money can't also count as savings.
    provision = (
        db.query(FlatRateProvisionSource)
        .filter(
            FlatRateProvisionSource.user_id == current_user.id,
            FlatRateProvisionSource.deleted_at.is_(None),
            FlatRateProvisionSource.account_id == account.id,
            FlatRateProvisionSource.asset_id == asset_id
            if asset_id is not None
            else FlatRateProvisionSource.asset_id.is_(None),
        )
        .first()
    )
    if provision is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This holds the tax provision — remove it from Fatture first",
        )

    source = SavingsGoalSource(goal_id=goal.id, account_id=account_id, asset_id=asset_id)
    db.add(source)
    db.flush()
    return source


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
    source = _link_source(db, current_user, goal, payload.account_id, payload.asset_id)
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
    source = next((s for s in goal.sources if s.id == source_id and s.deleted_at is None), None)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    source.deleted_at = datetime.now(UTC)
    db.commit()
