"""
Planning endpoints: the allocation plan itself, how the current period is
tracking against it, the survival budget, and the what-if simulator.

The heavy lifting lives in `services/planning.py` and
`services/necessity.py`; this file is validation plus wiring, following
the `_get_owned_*` shape the other routers use.
"""

from datetime import date as date_

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import AllocationPlan, Category, User
from app.schemas import (
    AllocationPlan as AllocationPlanSchema,
)
from app.schemas import (
    AllocationPlanUpdate,
    AllocationStatus,
    SimulationRequest,
    SimulationResponse,
    SurvivalBudget,
)
from app.services import planning as planning_service
from app.services.ownership import get_owned_account

router = APIRouter(prefix="/api/v1/planning", tags=["planning"])

_PERCENTAGE_FIELDS = ("pct_primary", "pct_useful", "pct_discretionary", "pct_savings")


def _validate_percentages(update_data: dict) -> None:
    """
    The four percentages are all-or-nothing, and must sum to exactly 100.

    Both rules are enforced in the database too, but a CheckConstraint
    violation would surface as a generic 500 — checking here turns it into
    a 422 that says which rule was broken.
    """
    provided = [field for field in _PERCENTAGE_FIELDS if field in update_data]
    if not provided:
        return

    if len(provided) != len(_PERCENTAGE_FIELDS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "All four percentages must be sent together "
                "(pct_primary, pct_useful, pct_discretionary, pct_savings)"
            ),
        )

    total = sum(update_data[field] for field in _PERCENTAGE_FIELDS)
    if total != 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"The four percentages must sum to 100 (got {total})",
        )


def _validate_cuts(db: Session, request: SimulationRequest, user: User) -> None:
    seen: set[object] = set()
    for cut in request.cuts:
        if (cut.category_id is None) == (cut.necessity_level is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Each cut must target exactly one of necessity_level or category_id",
            )

        key = cut.category_id or cut.necessity_level
        if key in seen:
            # Two cuts on the same target have no defined winner, and
            # silently picking one would quietly change the answer.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate cut for target '{key}'",
            )
        seen.add(key)

        if cut.category_id is not None:
            category = (
                db.query(Category)
                .filter(
                    Category.id == cut.category_id,
                    Category.user_id == user.id,
                    Category.deleted_at.is_(None),
                )
                .first()
            )
            if category is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
                )
            if category.type != "expense":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Only expense categories can be cut",
                )


@router.get("/plan", response_model=AllocationPlanSchema)
def get_plan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AllocationPlan:
    # Get-or-create rather than 404: a user without a plan can't be shown
    # anything useful, and the 50/25/15/10 preset is a sensible default for
    # everyone. Same lazy shape as the "Varie" category.
    return planning_service.get_or_create_plan(db, current_user)


@router.patch("/plan", response_model=AllocationPlanSchema)
def update_plan(
    payload: AllocationPlanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AllocationPlan:
    plan = planning_service.get_or_create_plan(db, current_user)
    update_data = payload.model_dump(exclude_unset=True)
    _validate_percentages(update_data)

    if update_data.get("default_source_account_id") is not None:
        source = get_owned_account(db, update_data["default_source_account_id"], current_user)
        if source.closed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"The account «{source.name}» is closed",
            )

    for field, value in update_data.items():
        setattr(plan, field, value)

    db.commit()
    db.refresh(plan)
    return plan


@router.get("/allocation-status", response_model=AllocationStatus)
def allocation_status(
    on_date: date_ = Query(default_factory=date_.today, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AllocationStatus:
    # `date` serves both the current month and any past one, the same way
    # /budgets/status does — one endpoint, no separate history route.
    return planning_service.allocation_status(db, current_user, on_date)


@router.get("/survival-budget", response_model=SurvivalBudget)
def survival_budget(
    on_date: date_ = Query(default_factory=date_.today, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SurvivalBudget:
    return planning_service.survival_budget(db, current_user, on_date)


@router.post("/simulate", response_model=SimulationResponse)
def simulate(
    payload: SimulationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimulationResponse:
    # A POST that writes nothing: the cut list is structured data a GET
    # can't carry cleanly. Nothing downstream of here mutates state.
    _validate_cuts(db, payload, current_user)
    on_date = payload.date or date_.today()
    return planning_service.simulate(db, current_user, payload, on_date)
