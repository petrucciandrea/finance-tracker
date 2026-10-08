"""
The waterfall savings engine.

The savings quota for a period fills the rungs of the ladder in priority
order, and only spills into the next once the one above is full. Three
properties fall out of that shape rather than being coded specially:

- **Refilling is free.** Drain the emergency fund and its gap reopens;
  having the lowest priority number, it is back at the top of the cascade
  next period with no dedicated branch.

- **An unknown target is not a met target.** A rung whose target depends
  on average primary spend is *skipped* while that average is unknown.
  Treating it as funded would release the entire quota to the rung below —
  the exact opposite of what a user with no history should be doing.

- **A funded rung stops asking.** A goal counts as funded at 95% of its
  target. Without that band a dynamic target creates a quiet pathology: a
  costly quarter raises the emergency fund's target, reopens a small gap,
  and — being top priority — it starves every rung below it indefinitely
  with micro top-ups.
"""

from datetime import date as date_
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models import Account, SavingsAllocation, SavingsGoal, User
from app.schemas import (
    SavingsGoalKind,
    TargetMode,
    WaterfallAction,
    WaterfallActionKind,
    WaterfallPlan,
    WaterfallStep,
)
from app.services.net_worth import account_balances
from app.services.periods import period_bounds
from app.services.planning import (
    average_monthly_primary_expenses,
    get_or_create_plan,
    income_base,
)

# A rung counts as funded here rather than at exactly 100% — see the
# module docstring on starvation.
FUNDED_THRESHOLD = Decimal("0.95")


def _quantize(amount: Decimal) -> Decimal:
    # ROUND_DOWN so the sum of allocations can never exceed the quota; the
    # sub-cent remainder surfaces as `unallocated_amount`.
    return amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def list_goals(db: Session, user: User) -> list[SavingsGoal]:
    """
    Goals in cascade order. `created_at` is the tiebreaker because
    `priority` is not unique — see the model for why it can't be.
    """
    return (
        db.query(SavingsGoal)
        .options(selectinload(SavingsGoal.sources))
        .filter(SavingsGoal.user_id == user.id, SavingsGoal.deleted_at.is_(None))
        .order_by(SavingsGoal.priority, SavingsGoal.created_at)
        .all()
    )


def _goal_target(
    goal: SavingsGoal, monthly_primary: Decimal | None
) -> tuple[Decimal | None, bool]:
    """Returns (target, unavailable). An open-ended rung has no target."""
    if goal.target_mode == TargetMode.fixed_amount.value:
        return Decimal(str(goal.target_amount)), False
    if goal.target_mode == TargetMode.months_of_primary_expenses.value:
        if monthly_primary is None:
            return None, True
        return _quantize(monthly_primary * Decimal(str(goal.target_months))), False
    return None, False  # open_ended


def allocated_in_period(db: Session, user: User, period_start: date_) -> Decimal:
    """
    How much of a period's savings quota has already been transferred.

    Executed giroconti raise the destination balance, which shrinks each
    goal's gap on its own — but the *quota* would still look untouched, so
    reloading the page would offer the same money again. This is what stops
    a user who follows the suggestions twice from double-transferring.
    """
    total = (
        db.query(func.coalesce(func.sum(SavingsAllocation.amount_base_currency), 0))
        .filter(
            SavingsAllocation.user_id == user.id,
            SavingsAllocation.period_start == period_start,
            SavingsAllocation.deleted_at.is_(None),
        )
        .scalar()
    )
    return Decimal(str(total))


def compute_waterfall(db: Session, user: User, on_date: date_) -> WaterfallPlan:
    """Build the cascade for the period containing `on_date`."""
    plan = get_or_create_plan(db, user)
    period_start, period_end = period_bounds("monthly", on_date)

    # Net of flat-rate taxes: a quota on gross invoices would send the
    # State's share up the savings ladder.
    base = income_base(db, user, date_from=period_start, date_to=period_end)
    income = base.net
    quota = _quantize(income * Decimal(str(plan.pct_savings)) / Decimal("100"))
    allocated_already = allocated_in_period(db, user, period_start)
    # Clamped: deleting an income after executing its transfers would
    # otherwise make the remainder negative and invert the cascade.
    remaining = max(Decimal("0"), quota - allocated_already)

    monthly_primary = average_monthly_primary_expenses(
        db, user, as_of=on_date, lookback_months=plan.lookback_months
    )

    goals = list_goals(db, user)
    balances = {b.account_id: b.balance_base_currency for b in account_balances(db, user)}
    accounts_by_id = {
        account.id: account
        for account in db.query(Account)
        .filter(Account.user_id == user.id, Account.deleted_at.is_(None))
        .all()
    }
    source_account = (
        accounts_by_id.get(plan.default_source_account_id)
        if plan.default_source_account_id
        else None
    )
    # Closed after being picked as the plan's source: suggesting transfers
    # out of it would only produce actions the execute endpoint refuses.
    if source_account is not None and source_account.closed_at is not None:
        source_account = None

    steps: list[WaterfallStep] = []
    actions: list[WaterfallAction] = []
    cascade_closed = False

    for goal in goals:
        source_ids = [s.account_id for s in goal.sources if s.deleted_at is None]
        current = sum((balances.get(aid, Decimal("0")) for aid in source_ids), Decimal("0"))
        target, unavailable = _goal_target(goal, monthly_primary)

        if cascade_closed or unavailable:
            # Either an open-ended rung above already took everything, or
            # this rung's target isn't knowable yet. Report it, allocate
            # nothing, and — crucially — don't mark it funded.
            steps.append(
                _step(goal, target, unavailable, current, Decimal("0"), is_funded=False)
            )
            continue

        if target is None:  # open_ended: absorbs the remainder and closes the cascade
            allocated = remaining
            remaining = Decimal("0")
            cascade_closed = True
            steps.append(_step(goal, None, False, current, allocated, is_funded=False))
        else:
            # max(0, ...): an overfunded rung must never "give money back".
            gap = max(Decimal("0"), target - current)
            is_funded = target > 0 and current >= target * FUNDED_THRESHOLD
            allocated = Decimal("0") if is_funded else _quantize(min(remaining, gap))
            remaining -= allocated
            steps.append(_step(goal, target, False, current, allocated, is_funded=is_funded))

        if allocated > 0:
            actions.append(
                _action(goal, allocated, source_ids, accounts_by_id, source_account, steps[-1])
            )

    return WaterfallPlan(
        base_currency=user.base_currency,
        period_start=period_start,
        period_end=period_end,
        income_total=_quantize(income),
        gross_income_total=_quantize(base.gross),
        flat_rate_tax_total=_quantize(base.flat_rate_taxes),
        savings_quota=quota,
        already_allocated=_quantize(allocated_already),
        steps=steps,
        unallocated_amount=_quantize(remaining),
        actions=actions,
    )


def _step(
    goal: SavingsGoal,
    target: Decimal | None,
    unavailable: bool,
    current: Decimal,
    allocated: Decimal,
    *,
    is_funded: bool,
) -> WaterfallStep:
    if target and target > 0:
        funding_percentage = round(float(current / target * 100), 1)
        gap = max(Decimal("0"), target - current)
    else:
        # An open-ended rung has no denominator, so a percentage would be
        # meaningless rather than 100.
        funding_percentage = 0.0
        gap = Decimal("0")

    return WaterfallStep(
        goal_id=goal.id,
        name=goal.name,
        kind=SavingsGoalKind(goal.kind),
        priority=goal.priority,
        target_mode=TargetMode(goal.target_mode),
        target_amount=target,
        target_unavailable=unavailable,
        current_amount=_quantize(current),
        gap=_quantize(gap),
        allocated_amount=_quantize(allocated),
        funding_percentage=funding_percentage,
        is_funded=is_funded,
    )


def _action(
    goal: SavingsGoal,
    amount: Decimal,
    source_ids: list[UUID],
    accounts_by_id: dict[UUID, Account],
    source_account: Account | None,
    step: WaterfallStep,
) -> WaterfallAction:
    """
    Turn an allocation into something the user can act on: an executable
    giroconto where one is possible, otherwise advice saying what is
    missing. Nothing is silently dropped.
    """
    # When a rung has several funding accounts, the oldest mapping wins —
    # `sources` comes back ordered by insertion, and picking arbitrarily
    # would make the suggestion flip between renders.
    destination = next(
        (accounts_by_id[aid] for aid in source_ids if aid in accounts_by_id), None
    )
    context = (
        f"{step.funding_percentage}% del target"
        if step.target_amount
        else "obiettivo senza target, assorbe il residuo"
    )

    if destination is None:
        reason = f"Nessun conto collegato a «{goal.name}» — {context}"
    elif source_account is None:
        reason = f"Imposta un conto di accredito nel piano per eseguirlo — {context}"
    elif source_account.id == destination.id:
        reason = f"Il conto di accredito è già quello dell'obiettivo — {context}"
    elif source_account.currency != destination.currency:
        reason = (
            f"Valute diverse ({source_account.currency} → {destination.currency}), "
            f"da fare a mano — {context}"
        )
    else:
        return WaterfallAction(
            kind=WaterfallActionKind.transfer,
            goal_id=goal.id,
            goal_name=goal.name,
            amount=amount,
            currency=destination.currency,
            from_account_id=source_account.id,
            from_account_name=source_account.name,
            to_account_id=destination.id,
            to_account_name=destination.name,
            reason=context,
        )

    return WaterfallAction(
        kind=WaterfallActionKind.advice,
        goal_id=goal.id,
        goal_name=goal.name,
        amount=amount,
        currency=destination.currency if destination else "",
        to_account_id=destination.id if destination else None,
        to_account_name=destination.name if destination else None,
        reason=reason,
    )
