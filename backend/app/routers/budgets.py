"""
Budgets endpoints: CRUD with soft delete, plus a parametric status endpoint
that computes spent-vs-limit for whichever period (month or year) contains
a given date — defaults to today (current period), but passing any past
date returns historical status for that period, so one endpoint covers
both "how am I doing this month" and "how did I do in July".
"""

import calendar
from datetime import date as date_
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.deps import get_current_user, get_db
from app.models import Budget, Category, Transaction, User
from app.schemas import (
    Budget as BudgetSchema,
    BudgetCreate,
    BudgetStatus,
    BudgetUpdate,
)

router = APIRouter(prefix="/api/v1/budgets", tags=["budgets"])


def _get_owned_budget(db: Session, budget_id: UUID, user: User) -> Budget:
    budget = (
        db.query(Budget)
        .filter(Budget.id == budget_id, Budget.user_id == user.id, Budget.deleted_at.is_(None))
        .first()
    )
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return budget


def _period_bounds(period: str, on_date: date_) -> tuple[date_, date_]:
    """Returns (start, end) inclusive dates for the month/year containing on_date."""
    if period == "monthly":
        start = on_date.replace(day=1)
        last_day = calendar.monthrange(on_date.year, on_date.month)[1]
        end = on_date.replace(day=last_day)
    else:  # yearly
        start = on_date.replace(month=1, day=1)
        end = on_date.replace(month=12, day=31)
    return start, end


@router.get("", response_model=list[BudgetSchema])
def list_budgets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Budget]:
    # No pagination: a personal user has at most one budget per expense
    # category, unlike transactions — unbounded growth isn't a concern here.
    return (
        db.query(Budget)
        .filter(Budget.user_id == current_user.id, Budget.deleted_at.is_(None))
        .order_by(Budget.start_date.desc())
        .all()
    )


@router.post("", response_model=BudgetSchema, status_code=status.HTTP_201_CREATED)
def create_budget(
    payload: BudgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Budget:
    category = (
        db.query(Category)
        .filter(
            Category.id == payload.category_id,
            Category.user_id == current_user.id,
            Category.deleted_at.is_(None),
        )
        .first()
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    if category.type != "expense":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Budgets can only be set on expense categories",
        )

    budget = Budget(
        user_id=current_user.id,
        category_id=payload.category_id,
        period=payload.period.value,
        amount_limit=payload.amount_limit,
        start_date=payload.start_date,
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@router.get("/status", response_model=list[BudgetStatus])
def budgets_status(
    on_date: date_ = Query(default_factory=date_.today, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetStatus]:
    budgets = (
        db.query(Budget)
        .options(joinedload(Budget.category))
        .filter(
            Budget.user_id == current_user.id,
            Budget.deleted_at.is_(None),
            Budget.start_date <= on_date,
        )
        .all()
    )

    results: list[BudgetStatus] = []
    for budget in budgets:
        period_start, period_end = _period_bounds(budget.period, on_date)
        # A budget's start_date can fall mid-period (e.g. created on the
        # 10th of the month) — only count spend from start_date onward,
        # never before the budget existed.
        effective_start = max(period_start, budget.start_date)

        spent = (
            db.query(func.coalesce(func.sum(Transaction.amount_base_currency), 0))
            .join(Category, Category.id == Transaction.category_id)
            .filter(
                Transaction.category_id == budget.category_id,
                Transaction.type == "expense",
                Transaction.deleted_at.is_(None),
                Transaction.date >= effective_start,
                Transaction.date <= period_end,
            )
            .scalar()
        )
        # Expenses are stored negative; a positive "amount spent" is more
        # intuitive to compare against a positive amount_limit.
        amount_spent = -Decimal(str(spent))

        percentage_used = (
            float(amount_spent / budget.amount_limit * 100) if budget.amount_limit else 0.0
        )

        results.append(
            BudgetStatus(
                category_id=budget.category_id,
                category_name=budget.category.name,
                period=budget.period,
                amount_limit=budget.amount_limit,
                amount_spent=amount_spent,
                percentage_used=round(percentage_used, 1),
                is_over_budget=amount_spent > budget.amount_limit,
            )
        )

    return results


@router.get("/{budget_id}", response_model=BudgetSchema)
def get_budget(
    budget_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Budget:
    return _get_owned_budget(db, budget_id, current_user)


@router.patch("/{budget_id}", response_model=BudgetSchema)
def update_budget(
    budget_id: UUID,
    payload: BudgetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Budget:
    budget = _get_owned_budget(db, budget_id, current_user)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(budget, field, value)
    db.commit()
    db.refresh(budget)
    return budget


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    budget_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    budget = _get_owned_budget(db, budget_id, current_user)
    budget.deleted_at = datetime.now(timezone.utc)
    db.commit()
