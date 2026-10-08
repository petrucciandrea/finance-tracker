"""
The allocation model (50/25/15/10), the survival budget, and the
what-if simulator.

Three decisions worth knowing before reading the code:

- **The income base is the period's real income**, not a declared salary,
  so every figure here moves with what actually landed in the accounts.
  `necessity.income_total` already clamps it at zero and drops categories
  opted out of the base.

- **Unclassified spend is never folded into a bucket.** It is reported
  alongside a coverage percentage, because a plan computed over half-
  classified data is not wrong so much as unknowable, and saying so is
  more useful than a confident wrong number.

- **An unknown average is None, never zero.** This is the sharpest edge in
  the module: a brand-new user has no complete month of history, and zero
  would mean "you need nothing to live on" — which in phase C also marks a
  dynamic emergency-fund target as already met, releasing the whole savings
  quota to the next goal down the ladder.
"""

from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Account, AllocationPlan, Transaction, User
from app.schemas import (
    AllocationBucket,
    AllocationBucketStatus,
    AllocationStatus,
    IncomeCategoryBreakdown,
    SimulatedBucket,
    SimulationRequest,
    SimulationResponse,
    SurvivalBudget,
)
from app.services.flat_rate import earmarked_cash
from app.services.necessity import (
    UNCLASSIFIED,
    classification_coverage,
    income_by_category,
    income_total,
    spend_by_necessity,
    spend_by_necessity_and_category,
)
from app.services.net_worth import total_cash_balance
from app.services.periods import add_months, month_start, months_between, period_bounds

# The preset the requirement names. Stored per user on first read rather
# than hardcoded at read time, so changing it later doesn't silently
# rewrite every existing user's plan.
DEFAULT_PERCENTAGES = {
    "pct_primary": Decimal("50"),
    "pct_useful": Decimal("25"),
    "pct_discretionary": Decimal("15"),
    "pct_savings": Decimal("10"),
}
DEFAULT_LOOKBACK_MONTHS = 6

# The three spend buckets, in the order they are reported.
SPEND_BUCKETS = (
    AllocationBucket.primary,
    AllocationBucket.useful,
    AllocationBucket.discretionary,
)

_PERCENTAGE_FIELD = {
    AllocationBucket.primary: "pct_primary",
    AllocationBucket.useful: "pct_useful",
    AllocationBucket.discretionary: "pct_discretionary",
    AllocationBucket.savings: "pct_savings",
}


def get_or_create_plan(db: Session, user: User) -> AllocationPlan:
    """
    The user's live plan, created with the preset on first read.

    Takes the oldest surviving row rather than asserting there is exactly
    one: there is no unique index on `user_id` (see the model for why), so
    a concurrent first read can leave a duplicate. Ordering makes the
    choice deterministic whether or not that ever happens.
    """
    plan = (
        db.query(AllocationPlan)
        .filter(AllocationPlan.user_id == user.id, AllocationPlan.deleted_at.is_(None))
        .order_by(AllocationPlan.created_at, AllocationPlan.id)
        .first()
    )
    if plan is not None:
        return plan

    plan = AllocationPlan(
        user_id=user.id, lookback_months=DEFAULT_LOOKBACK_MONTHS, **DEFAULT_PERCENTAGES
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def _percentage(plan: AllocationPlan, bucket: AllocationBucket) -> Decimal:
    return Decimal(str(getattr(plan, _PERCENTAGE_FIELD[bucket])))


def _quantize_money(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"))


def allocation_status(db: Session, user: User, on_date: date_) -> AllocationStatus:
    """Planned split vs what actually happened, for the month containing on_date."""
    plan = get_or_create_plan(db, user)
    period_start, period_end = period_bounds("monthly", on_date)

    income = income_total(db, user, date_from=period_start, date_to=period_end)
    buckets = spend_by_necessity(db, user, date_from=period_start, date_to=period_end)

    unclassified = buckets.get(UNCLASSIFIED, Decimal("0"))
    total_spend = sum(buckets.values(), Decimal("0"))

    statuses: list[AllocationBucketStatus] = []
    for bucket in SPEND_BUCKETS:
        statuses.append(
            _bucket_status(
                bucket,
                percentage=_percentage(plan, bucket),
                income=income,
                actual=buckets.get(bucket.value, Decimal("0")),
            )
        )

    # Savings is the residual: what income was left after every expense,
    # unclassified included. Deriving it from spend rather than from
    # transfers into savings accounts keeps it honest — money not spent is
    # saved whether or not it has been moved yet.
    statuses.append(
        _bucket_status(
            AllocationBucket.savings,
            percentage=_percentage(plan, AllocationBucket.savings),
            income=income,
            actual=income - total_spend,
        )
    )

    return AllocationStatus(
        base_currency=user.base_currency,
        period_start=period_start,
        period_end=period_end,
        income_total=_quantize_money(income),
        buckets=statuses,
        unclassified_amount=_quantize_money(unclassified),
        classification_coverage=classification_coverage(buckets),
        income_breakdown=[
            IncomeCategoryBreakdown(
                category_id=row["category_id"],
                category_name=row["category_name"],
                excluded_from_income_base=row["excluded_from_income_base"],
                total_amount_base_currency=_quantize_money(
                    row["total_amount_base_currency"]
                ),
            )
            for row in income_by_category(
                db, user, date_from=period_start, date_to=period_end
            )
        ],
    )


def _bucket_status(
    bucket: AllocationBucket, *, percentage: Decimal, income: Decimal, actual: Decimal
) -> AllocationBucketStatus:
    target = income * percentage / Decimal("100")
    percentage_used = float(actual / target * 100) if target else 0.0
    return AllocationBucketStatus(
        bucket=bucket,
        percentage=percentage,
        target_amount=_quantize_money(target),
        actual_amount=_quantize_money(actual),
        deviation=_quantize_money(target - actual),
        percentage_used=round(percentage_used, 1),
        is_over_target=actual > target,
    )


def _first_transaction_date(db: Session, user: User) -> date_ | None:
    return (
        db.query(func.min(Transaction.date))
        .join(Account, Account.id == Transaction.account_id)
        .filter(Account.user_id == user.id, Transaction.deleted_at.is_(None))
        .scalar()
    )


def _analysis_window(
    db: Session, user: User, *, as_of: date_, lookback_months: int
) -> tuple[date_, date_, int] | None:
    """
    The complete months the averages are computed over, as
    `(start, end, month_count)`.

    The window ends with the month *before* the one containing `as_of`: a
    month still in progress would drag every average down simply by not
    having finished yet.

    It starts at the later of the lookback window and the user's first
    transaction, and counts only whole months in between. Counting "months
    since the first transaction" instead would give full weight to a first
    month that began on the 25th. Returns None when that leaves nothing —
    which is the signal callers turn into "unavailable", never into zero.
    """
    window_end = add_months(month_start(as_of), -1)
    window_start = add_months(window_end, -(lookback_months - 1))

    first_transaction = _first_transaction_date(db, user)
    if first_transaction is None:
        return None

    effective_start = max(window_start, month_start(first_transaction))
    if effective_start > window_end:
        return None

    month_count = months_between(effective_start, window_end) + 1
    _, end_of_window = period_bounds("monthly", window_end)
    return effective_start, end_of_window, month_count


def average_monthly_primary_expenses(
    db: Session, user: User, *, as_of: date_, lookback_months: int
) -> Decimal | None:
    """
    Mean monthly spend on primary-necessity categories — the survival
    budget, and the multiplier behind phase C's dynamic emergency-fund
    target. None when there is no complete month to average.
    """
    window = _analysis_window(db, user, as_of=as_of, lookback_months=lookback_months)
    if window is None:
        return None

    start, end, month_count = window
    buckets = spend_by_necessity(db, user, date_from=start, date_to=end)
    primary = buckets.get(AllocationBucket.primary.value, Decimal("0"))
    return _quantize_money(primary / month_count)


def survival_budget(db: Session, user: User, on_date: date_) -> SurvivalBudget:
    plan = get_or_create_plan(db, user)
    window = _analysis_window(db, user, as_of=on_date, lookback_months=plan.lookback_months)
    # Cash set aside for the P.IVA's taxes is already the State's: counting
    # it as runway would promise months of living off money that's owed.
    cash = total_cash_balance(db, user) - earmarked_cash(db, user)

    if window is None:
        return SurvivalBudget(
            base_currency=user.base_currency,
            lookback_months=plan.lookback_months,
            months_analysed=0,
            total_cash_balance=_quantize_money(cash),
        )

    start, end, month_count = window
    buckets = spend_by_necessity(db, user, date_from=start, date_to=end)
    monthly_primary = _quantize_money(
        buckets.get(AllocationBucket.primary.value, Decimal("0")) / month_count
    )
    monthly_total = _quantize_money(sum(buckets.values(), Decimal("0")) / month_count)
    monthly_income = _quantize_money(
        income_total(db, user, date_from=start, date_to=end) / month_count
    )

    return SurvivalBudget(
        base_currency=user.base_currency,
        lookback_months=plan.lookback_months,
        months_analysed=month_count,
        monthly_primary_expenses=monthly_primary,
        monthly_total_expenses=monthly_total,
        monthly_income=monthly_income,
        total_cash_balance=_quantize_money(cash),
        # A zero survival budget means "we don't know yet", not "infinite
        # runway", so it yields None rather than a division by zero.
        months_of_runway=(
            round(float(cash / monthly_primary), 1) if monthly_primary > 0 else None
        ),
    )


def simulate(
    db: Session, user: User, request: SimulationRequest, on_date: date_
) -> SimulationResponse:
    """
    Apply hypothetical spending cuts to the period's actual spend.

    Read-only despite being a POST — the body is structured, which a GET
    can't carry cleanly. Nothing here writes.

    Precedence: a cut aimed at a specific category wins over a cut aimed at
    the bucket containing it, and that category is then excluded from the
    bucket cut's base. Without the rule, "cut discretionary by 50%" plus
    "cut Netflix by 100%" would free Netflix's spend one and a half times.
    """
    plan = get_or_create_plan(db, user)
    period_start, period_end = period_bounds("monthly", on_date)

    income = income_total(db, user, date_from=period_start, date_to=period_end)
    rows = spend_by_necessity_and_category(
        db, user, date_from=period_start, date_to=period_end
    )

    category_cuts: dict[UUID | None, Decimal] = {}
    bucket_cuts: dict[str | None, Decimal] = {}
    for cut in request.cuts:
        if cut.category_id is not None:
            category_cuts[cut.category_id] = cut.cut_percentage
        elif cut.necessity_level is not None:
            bucket_cuts[cut.necessity_level.value] = cut.cut_percentage

    baseline_by_bucket: dict[str | None, Decimal] = {}
    freed_by_bucket: dict[str | None, Decimal] = {}
    for bucket, category_id, amount in rows:
        baseline_by_bucket[bucket] = baseline_by_bucket.get(bucket, Decimal("0")) + amount

        if category_id in category_cuts:
            cut_percentage = category_cuts[category_id]
        elif bucket in bucket_cuts:
            cut_percentage = bucket_cuts[bucket]
        else:
            cut_percentage = Decimal("0")

        freed = amount * cut_percentage / Decimal("100")
        freed_by_bucket[bucket] = freed_by_bucket.get(bucket, Decimal("0")) + freed

    simulated_buckets: list[SimulatedBucket] = []
    for bucket in SPEND_BUCKETS:
        baseline = baseline_by_bucket.get(bucket.value, Decimal("0"))
        freed = freed_by_bucket.get(bucket.value, Decimal("0"))
        simulated_buckets.append(
            SimulatedBucket(
                bucket=bucket,
                baseline_amount=_quantize_money(baseline),
                simulated_amount=_quantize_money(baseline - freed),
                freed_amount=_quantize_money(freed),
            )
        )

    # Unclassified spend is cut too when a bucket cut can't reach it — it
    # can't, by definition — so it stays in both totals untouched, and the
    # savings figures below stay comparable with allocation_status.
    total_baseline = sum(baseline_by_bucket.values(), Decimal("0"))
    total_freed = sum(freed_by_bucket.values(), Decimal("0"))
    total_simulated = total_baseline - total_freed

    baseline_savings = income - total_baseline
    simulated_savings = income - total_simulated

    baseline_primary = baseline_by_bucket.get(AllocationBucket.primary.value, Decimal("0"))
    freed_primary = freed_by_bucket.get(AllocationBucket.primary.value, Decimal("0"))
    baseline_survival = average_monthly_primary_expenses(
        db, user, as_of=on_date, lookback_months=plan.lookback_months
    )
    # Scale the historical average by the same proportion the cuts remove
    # from this period's primary spend — i.e. "if you made these cuts
    # permanent". An approximation, since the cuts are derived from one
    # period and applied to an average of several.
    simulated_survival = baseline_survival
    if baseline_survival is not None and baseline_primary > 0:
        retained = (baseline_primary - freed_primary) / baseline_primary
        simulated_survival = _quantize_money(baseline_survival * retained)

    return SimulationResponse(
        base_currency=user.base_currency,
        period_start=period_start,
        period_end=period_end,
        income_total=_quantize_money(income),
        buckets=simulated_buckets,
        total_baseline_spend=_quantize_money(total_baseline),
        total_simulated_spend=_quantize_money(total_simulated),
        total_freed=_quantize_money(total_freed),
        baseline_savings_amount=_quantize_money(baseline_savings),
        simulated_savings_amount=_quantize_money(simulated_savings),
        baseline_savings_rate=round(float(baseline_savings / income * 100), 1) if income else 0.0,
        simulated_savings_rate=round(float(simulated_savings / income * 100), 1) if income else 0.0,
        baseline_survival_budget=baseline_survival,
        simulated_survival_budget=simulated_survival,
    )
