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

A medium-term goal can carry a **date**. The cascade doesn't change for it
— it still runs on `priority`, and a new dated goal is merely *placed* by
its date — but its step also says what each month must bring to arrive on
time, what this month actually brings, and when the gap closes at that
pace. A goal marked reached (`completed_at`) leaves the cascade.

A source is an account's cash or one holding in it. Holdings are valued from
the caches only (`cached_holding_values`), so this module still never calls
out.
"""

import math
from dataclasses import dataclass
from datetime import date as date_
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models import Account, SavingsAllocation, SavingsGoal, User
from app.schemas import (
    AccountAmount,
    SavingsGoalKind,
    TargetMode,
    TaxProvisionRung,
    WaterfallAction,
    WaterfallActionKind,
    WaterfallPlan,
    WaterfallStep,
)
from app.services import flat_rate
from app.services.net_worth import (
    account_balances,
    cached_holding_values,
    compute_holding_positions,
    latest_cached_rate,
)
from app.services.operating_cash import operating_cash
from app.services.periods import add_months, month_start, months_between, period_bounds
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


def list_goals(db: Session, user: User, *, include_completed: bool = True) -> list[SavingsGoal]:
    """
    Goals in cascade order. `created_at` is the tiebreaker because
    `priority` is not unique — see the model for why it can't be.
    """
    query = (
        db.query(SavingsGoal)
        .options(selectinload(SavingsGoal.sources))
        .filter(SavingsGoal.user_id == user.id, SavingsGoal.deleted_at.is_(None))
    )
    if not include_completed:
        query = query.filter(SavingsGoal.completed_at.is_(None))
    return query.order_by(SavingsGoal.priority, SavingsGoal.created_at).all()


def active_sources(goal: SavingsGoal) -> list:
    return [s for s in goal.sources if s.deleted_at is None]


def destination_account_id(goal: SavingsGoal) -> UUID | None:
    """
    Where a giroconto for the goal lands: its first cash source, else the
    account of its first holding (the money arrives as cash, and buying the
    product is the user's own step). Oldest mapping first — `sources` comes
    back in insertion order, and picking arbitrarily would flip between
    renders.
    """
    sources = active_sources(goal)
    cash = next((s.account_id for s in sources if s.asset_id is None), None)
    return cash if cash is not None else next((s.account_id for s in sources), None)


@dataclass
class GoalValues:
    # Per goal: (current amount in base currency, has an unpriced holding).
    current: dict[UUID, tuple[Decimal, bool]]
    # Per cash-source account: what's left once every goal it funds is full.
    excess: dict[UUID, Decimal]


def goal_values(
    db: Session,
    user: User,
    goals: list[SavingsGoal],
    monthly_primary: Decimal | None,
) -> GoalValues:
    """
    What each goal already holds, splitting shared accounts **in cascade
    order**: an account funding the emergency fund and the holiday fills the
    emergency fund up to its target first, then the holiday; what is left
    once all of them are full is that account's *excess* — free money the
    cascade can move on. A goal whose target is open (open-ended) or not yet
    knowable takes whatever is left, so no excess is claimed on a guess.

    Holdings are not split: a holding funds one goal (an ETF can't be moved by
    giroconto) and counts whole. A holding without a cached price counts as
    nothing *and says so*: the goal reads as less funded than it may be.
    """
    balances = {b.account_id: b.balance_base_currency for b in account_balances(db, user)}
    needs_holdings = any(s.asset_id for g in goals for s in active_sources(g))
    holdings = (
        cached_holding_values(db, user, compute_holding_positions(db, user))
        if needs_holdings
        else {}
    )
    left: dict[UUID, Decimal] = {}
    current: dict[UUID, tuple[Decimal, bool]] = {}
    for goal in goals:  # cascade order
        target, unavailable = _goal_target(goal, monthly_primary)
        cap = None if (target is None or unavailable) else target
        taken = Decimal("0")
        unpriced = False
        for source in active_sources(goal):
            if source.asset_id is None:
                continue
            value = holdings.get((source.account_id, source.asset_id))
            if value is None:
                # Either sold out since it was mapped (worth nothing, rightly)
                # or not priced: only the latter is a gap in the data.
                unpriced = unpriced or (source.account_id, source.asset_id) in holdings
            else:
                taken += value
        for source in active_sources(goal):
            if source.asset_id is not None:
                continue
            available = left.setdefault(
                source.account_id, balances.get(source.account_id, Decimal("0"))
            )
            if available <= 0:
                # An overdrawn account lowers the first goal it funds, once.
                taken += available
                left[source.account_id] = Decimal("0")
                continue
            take = available if cap is None else min(available, max(Decimal("0"), cap - taken))
            taken += take
            left[source.account_id] = available - take
        current[goal.id] = (taken, unpriced)
    return GoalValues(current=current, excess={a: v for a, v in left.items() if v > 0})


def allocated_by_goal(db: Session, user: User, period_start: date_) -> dict[UUID, Decimal]:
    rows = (
        db.query(SavingsAllocation.goal_id, func.sum(SavingsAllocation.amount_base_currency))
        .filter(
            SavingsAllocation.user_id == user.id,
            SavingsAllocation.period_start == period_start,
            SavingsAllocation.deleted_at.is_(None),
        )
        .group_by(SavingsAllocation.goal_id)
        .all()
    )
    return {goal_id: Decimal(str(total)) for goal_id, total in rows}


def _goal_target(goal: SavingsGoal, monthly_primary: Decimal | None) -> tuple[Decimal | None, bool]:
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

    goals = list_goals(db, user, include_completed=False)
    values = goal_values(db, user, goals, monthly_primary)
    executed = allocated_by_goal(db, user, period_start)
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

    # Not just this month's quota: whatever the operating accounts hold
    # beyond pillar 1's target is money with no job either. The quota's own
    # money already sits in that surplus (income lands on those accounts),
    # so the cascade distributes the larger of the two, never their sum.
    # Balances are always today's, so everything weighed against them is
    # taken today too, whatever day of the month was asked for: the tax
    # requirement at the 1st would miss an invoice collected on the 26th
    # while its money already sits in the balance, and hand the State's share
    # to the goals. `on_date` only picks the period (the quota, the
    # allocations already made).
    now = date_.today()
    # And only for the month in progress: today's balances say nothing about
    # a month already closed (or not begun), which reads on its quota alone.
    is_current = period_start <= now <= period_end
    operating = operating_cash(db, user, now)
    # No source picked in the plan: propose the operating account holding the
    # most cash rather than only advising "set one" — every suggestion stays
    # executable, and the client lets the user pick another one per row.
    source_is_fallback = False
    if source_account is None:
        source_account = next(
            (a for a, b in operating.accounts if b > 0 and a.closed_at is None), None
        )
        source_is_fallback = source_account is not None
    surplus = operating.surplus if is_current else None
    budget = remaining
    if surplus is not None and surplus > remaining:
        budget = surplus
        if source_account is not None:
            # Every suggested giroconto leaves the source account: offering
            # more than it holds would only produce transfers that overdraw it.
            held = next((b for a, b in operating.accounts if a.id == source_account.id), None)
            if held is not None:
                budget = max(remaining, min(budget, held))
    budget = _quantize(budget)

    # Where the money comes from, drawn in this order: the operating pool
    # (quota or surplus, leaving the source account), then each goal
    # account's excess, leaving that account. A rung's allocation may take
    # from several pools and then becomes one giroconto per pool.
    pools: list[_Pool] = [_Pool(source_account, budget)]
    for account_id, amount in sorted(
        values.excess.items() if is_current else [], key=lambda kv: -kv[1]
    ):
        account = accounts_by_id.get(account_id)
        if account is not None and account.closed_at is None and amount >= Decimal("0.01"):
            pools.append(_Pool(account, _quantize(amount)))
    # Snapshot for the response: drawing below consumes the pools.
    excess_pools = [_Pool(p.account, p.amount) for p in pools[1:]]
    excess_total = sum((p.amount for p in excess_pools), Decimal("0"))
    budget = _quantize(budget + excess_total)
    remaining = budget

    steps: list[WaterfallStep] = []
    actions: list[WaterfallAction] = []
    cascade_closed = False
    rungs: list[_Rung] = []

    tax_rung = _tax_provision_rung(db, user, now, remaining) if is_current else None
    if tax_rung is not None and tax_rung.allocated_amount > 0:
        pieces = _draw(pools, tax_rung.allocated_amount, tax_rung.account_id)
        tax_rung.allocated_amount = _quantize(sum((a for _, a in pieces), Decimal("0")))
        remaining -= tax_rung.allocated_amount
        for pool_account, amount in pieces:
            actions.append(
                _make_action(
                    None,
                    "Accantonamento tasse",
                    "tax_provision",
                    amount,
                    tax_rung.account_id,
                    accounts_by_id,
                    pool_account,
                    "quanto manca a ciò che chiederanno gli F24",
                )
            )

    for goal in goals:
        destination_id = destination_account_id(goal)
        current, unpriced = values.current[goal.id]
        target, unavailable = _goal_target(goal, monthly_primary)

        if cascade_closed or unavailable:
            # Either an open-ended rung above already took everything, or
            # this rung's target isn't knowable yet. Report it, allocate
            # nothing, and — crucially — don't mark it funded.
            steps.append(_step(goal, target, unavailable, current, Decimal("0"), is_funded=False))
            continue

        if target is None:  # open_ended: absorbs the remainder and closes the cascade
            pieces = _draw(pools, remaining, destination_id)
            allocated = _quantize(sum((a for _, a in pieces), Decimal("0")))
            remaining -= allocated
            cascade_closed = True
            steps.append(_step(goal, None, False, current, allocated, is_funded=False))
        else:
            # max(0, ...): an overfunded rung must never "give money back".
            gap = max(Decimal("0"), target - current)
            is_funded = target > 0 and current >= target * FUNDED_THRESHOLD
            wanted = Decimal("0") if is_funded else _quantize(min(remaining, gap))
            pieces = _draw(pools, wanted, destination_id) if wanted > 0 else []
            allocated = _quantize(sum((a for _, a in pieces), Decimal("0")))
            remaining -= allocated
            steps.append(_step(goal, target, False, current, allocated, is_funded=is_funded))

        steps[-1].has_unpriced_sources = unpriced
        rungs.append(_Rung(goal, steps[-1], target, unavailable, current, allocated))

        for pool_account, amount in pieces if allocated > 0 else []:
            actions.append(
                _action(goal, amount, destination_id, accounts_by_id, pool_account, steps[-1])
            )

    # Timetables last: they need what the quota alone would give each goal
    # next month, which depends on the whole cascade.
    recurring = _recurring_shares(rungs, quota)
    for r in rungs:
        if r.goal.target_date is not None and r.target is not None:
            _schedule(
                r.step,
                r.goal,
                r.target,
                r.current,
                executed.get(r.goal.id, Decimal("0")),
                r.allocated,
                recurring.get(r.goal.id, Decimal("0")),
                period_start,
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
        operating_surplus=_quantize(surplus) if surplus is not None else None,
        source_account_id=source_account.id if source_account else None,
        source_is_fallback=source_is_fallback,
        budget=budget,
        tax_provision=tax_rung,
        goal_account_excess=_quantize(excess_total),
        goal_account_excesses=[
            AccountAmount(account_id=p.account.id, account_name=p.account.name, amount=p.amount)
            for p in excess_pools
            if p.account is not None
        ],
    )


@dataclass
class _Rung:
    goal: SavingsGoal
    step: WaterfallStep
    target: Decimal | None
    unavailable: bool
    current: Decimal
    allocated: Decimal


@dataclass
class _Pool:
    account: Account | None
    amount: Decimal


def _draw(
    pools: list[_Pool], amount: Decimal, destination_id: UUID | None
) -> list[tuple[Account | None, Decimal]]:
    """
    Take `amount` from the pools in order, skipping the one that *is* the
    destination (moving money within an account does nothing). Returns
    (source account, amount) pieces; their sum may fall short of `amount`.
    """
    pieces: list[tuple[Account | None, Decimal]] = []
    for pool in pools:
        if amount <= 0:
            break
        if pool.amount <= 0:
            continue
        if (
            destination_id is not None
            and pool.account is not None
            and pool.account.id == destination_id
        ):
            continue
        take = _quantize(min(pool.amount, amount))
        if take <= 0:
            continue
        pool.amount -= take
        amount -= take
        pieces.append((pool.account, take))
    return pieces


def _tax_provision_rung(
    db: Session, user: User, on_date: date_, budget: Decimal
) -> TaxProvisionRung | None:
    """
    The P.IVA provision before any goal: what the F24s will still ask for the
    income collected so far, less what's already scheduled from accounts
    outside the provision (those debits come out of pillar 1, where they are
    already subtracted from the surplus), against what the provision holds.
    Cache-only like the rest: no cached EUR rate for a non-EUR user = no rung.
    """
    sources = flat_rate.active_sources(db, user)
    cash_ids = [s.account_id for s in sources if s.asset_id is None]
    if not cash_ids:
        return None
    rate = latest_cached_rate(db, flat_rate.CURRENCY, user.base_currency, on_date)
    if rate is None:
        return None
    ledger = flat_rate.load_ledger(db, user)
    scheduled_elsewhere = sum(
        (Decimal(str(p.amount)) for p in ledger.scheduled if p.account_id not in cash_ids),
        Decimal("0"),
    )
    target = max(Decimal("0"), flat_rate.cash_requirement(ledger, on_date) - scheduled_elsewhere)
    target = _quantize(target * rate)

    balances = {b.account_id: b.balance_base_currency for b in account_balances(db, user)}
    current = sum((balances.get(aid, Decimal("0")) for aid in cash_ids), Decimal("0"))
    holdings = [(s.account_id, s.asset_id) for s in sources if s.asset_id is not None]
    if holdings:
        values = cached_holding_values(db, user, compute_holding_positions(db, user), on_date)
        current += sum((values.get(k) or Decimal("0") for k in holdings), Decimal("0"))
    gap = max(Decimal("0"), target - current)
    account = db.get(Account, cash_ids[0])
    return TaxProvisionRung(
        target=target,
        current=_quantize(current),
        gap=_quantize(gap),
        allocated_amount=_quantize(min(budget, gap)),
        account_id=cash_ids[0],
        account_name=account.name if account else None,
    )


def _recurring_shares(rungs: list[_Rung], quota: Decimal) -> dict[UUID, Decimal]:
    """
    What the monthly quota alone would give each goal from next month on: the
    same cascade, run on the full quota, over the gaps as they will stand
    once this month's suggestions are done (an emergency fund filled today
    stops asking tomorrow). The one-off surplus is deliberately left out —
    it is a stock, and projecting it as if it came back every month would
    call any goal "on track".
    """
    left = quota
    shares: dict[UUID, Decimal] = {}
    for r in rungs:
        if r.unavailable:
            continue
        if r.target is None:  # open-ended: takes the rest, and closes the cascade
            shares[r.goal.id] = left
            break
        after = r.current + r.allocated
        if r.target > 0 and after >= r.target * FUNDED_THRESHOLD:
            continue
        take = min(left, max(Decimal("0"), r.target - after))
        shares[r.goal.id] = take
        left -= take
    return shares


def _schedule(
    step: WaterfallStep,
    goal: SavingsGoal,
    target: Decimal,
    current: Decimal,
    executed: Decimal,
    suggested: Decimal,
    recurring: Decimal,
    period_start: date_,
) -> None:
    """
    A dated goal's timetable, in two parts: what this month puts aside
    (giroconti already executed + the suggestion still pending, one-off
    surplus included), and what the monthly quota brings from next month on.

    The gap is taken as it stood *before* this month's executed giroconti
    (they already raised the balance), so executing one doesn't change the
    timetable. The rate still needed is over what's left after this month,
    across the months after it.
    """
    assert goal.target_date is not None
    target_month = month_start(goal.target_date)
    months_left = (
        months_between(period_start, target_month) + 1 if target_month >= period_start else 0
    )
    gap_at_start = max(Decimal("0"), target - current + executed)
    this_month = executed + suggested
    after = max(Decimal("0"), gap_at_start - this_month)

    step.target_date = goal.target_date
    step.months_left = months_left
    step.this_month_amount = _quantize(this_month)
    step.monthly_pace = _quantize(recurring)
    if gap_at_start == 0 or step.is_funded or after == 0:
        step.required_monthly = Decimal("0.00")
        step.projected_date = period_start
        step.on_track = True
        return

    months_after = max(0, months_left - 1)
    required = after / months_after if months_after else after
    # Rounded up to the cent: rounding down would call a goal on track that
    # ends a few cents short.
    step.required_monthly = required.quantize(Decimal("0.01"), rounding=ROUND_UP)
    step.on_track = months_after > 0 and recurring >= step.required_monthly
    step.projected_date = (
        add_months(period_start, math.ceil(after / recurring)) if recurring > 0 else None
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
    destination_id: UUID | None,
    accounts_by_id: dict[UUID, Account],
    source_account: Account | None,
    step: WaterfallStep,
) -> WaterfallAction:
    context = (
        f"{step.funding_percentage}% del target"
        if step.target_amount
        else "obiettivo senza target, assorbe il residuo"
    )
    return _make_action(
        goal.id, goal.name, "goal", amount, destination_id, accounts_by_id, source_account, context
    )


def _make_action(
    goal_id: UUID | None,
    name: str,
    purpose: str,
    amount: Decimal,
    destination_id: UUID | None,
    accounts_by_id: dict[UUID, Account],
    source_account: Account | None,
    context: str,
) -> WaterfallAction:
    """
    Turn an allocation into something the user can act on: an executable
    giroconto where one is possible, otherwise advice saying what is
    missing. Nothing is silently dropped.
    """
    destination = accounts_by_id.get(destination_id) if destination_id else None

    if destination is None:
        reason = f"Nessun conto collegato a «{name}» — {context}"
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
            goal_id=goal_id,
            goal_name=name,
            purpose=purpose,
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
        goal_id=goal_id,
        goal_name=name,
        purpose=purpose,
        amount=amount,
        currency=destination.currency if destination else "",
        to_account_id=destination.id if destination else None,
        to_account_name=destination.name if destination else None,
        reason=reason,
    )
