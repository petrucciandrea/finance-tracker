"""
The plan's alerts: goals with a date, the portfolio guardrails, and two
habits worth a word (investing while the emergency fund has a hole, weights
older than a year).

Same contract as the rest of `services/alerts.py`: computed on read, never
a network call (holdings are valued from the caches), structured rather
than worded. All of them are `once` with an id carrying the month (or the
date they are about): allocations move with prices every day, and a banner
that comes back on each visit for a band crossed by a few tenths would be
dismissed unread. A new month, or a new cause, warns again.
"""

from datetime import date as date_
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, AssetTransaction, PortfolioRule, SavingsGoal, User
from app.schemas import (
    Alert,
    AlertRepeat,
    AlertTone,
    ExposureDimension,
    PillarKey,
    PillarsResponse,
    PortfolioRuleKind,
    RuleState,
    SavingsGoalKind,
)
from app.services.net_worth import (
    account_balances,
    cached_holding_values,
    compute_holding_positions,
)
from app.services.periods import add_months, month_start
from app.services.pillars import build_pillars
from app.services.portfolio_allocation import allocation, resolve_exposures
from app.services.portfolio_rules import evaluate
from app.services.waterfall import active_sources, list_goals

LEAD_DAYS = 14
# A goal due within this many years shouldn't sit mostly in equities or
# crypto: a 30% drawdown a year before the down payment is not recovered
# in time.
SHORT_HORIZON_YEARS = 3
RISKY_ASSET_CLASSES = ("equity", "crypto")
RISKY_SHARE = Decimal("50")


def plan_alerts(db: Session, user: User, today: date_) -> list[Alert]:
    has_goals = (
        db.query(SavingsGoal.id)
        .filter(SavingsGoal.user_id == user.id, SavingsGoal.deleted_at.is_(None))
        .first()
    )
    has_rules = db.query(PortfolioRule.id).filter(PortfolioRule.user_id == user.id).first()
    has_holdings = any(p["quantity"] > 0 for p in compute_holding_positions(db, user).values())
    if not (has_goals or has_rules or has_holdings):
        return []

    month = today.strftime("%Y-%m")
    pillars = build_pillars(db, user, today)
    alerts = [
        *_goal_alerts(pillars, today),
        *_horizon_alerts(db, user, today),
        *_emergency_alerts(db, user, pillars, today, month),
    ]
    if has_rules:
        alerts += _rule_alerts(db, user, pillars, today, month)
    if has_holdings:
        alerts += _stale_alerts(db, user, today)
    return alerts


def _goal_alerts(pillars: PillarsResponse, today: date_) -> list[Alert]:
    alerts: list[Alert] = []
    horizon = today + timedelta(days=LEAD_DAYS)
    currency = pillars.base_currency
    for pillar in pillars.pillars:
        for step in pillar.steps:
            if step.target_date is None or step.is_funded:
                continue
            if step.target_date < today and step.gap > 0:
                alerts.append(
                    Alert(
                        id=f"goal_overdue:{step.goal_id}:{step.target_date.isoformat()}",
                        kind="goal_overdue",
                        tone=AlertTone.danger,
                        repeat=AlertRepeat.once,
                        label=step.name,
                        due_date=step.target_date,
                        amount=step.gap,
                        currency=currency,
                        link="/planning",
                    )
                )
            elif step.target_date <= horizon:
                alerts.append(
                    Alert(
                        id=f"goal_due:{step.goal_id}:{step.target_date.isoformat()}",
                        kind="goal_due_soon",
                        tone=AlertTone.warn,
                        repeat=AlertRepeat.once,
                        label=step.name,
                        due_date=step.target_date,
                        amount=step.gap,
                        currency=currency,
                        link="/planning",
                    )
                )
            elif step.on_track is False:
                alerts.append(
                    Alert(
                        id=f"goal_behind:{step.goal_id}:{today.strftime('%Y-%m')}",
                        kind="goal_behind_schedule",
                        tone=AlertTone.warn,
                        repeat=AlertRepeat.once,
                        label=step.name,
                        due_date=step.projected_date,
                        amount=step.required_monthly,
                        currency=currency,
                        link="/planning",
                    )
                )
    return alerts


def _horizon_alerts(db: Session, user: User, today: date_) -> list[Alert]:
    """A goal due within three years funded mostly by equity or crypto."""
    cutoff = add_months(today, 12 * SHORT_HORIZON_YEARS)
    goals = [
        g
        for g in list_goals(db, user, include_completed=False)
        if g.kind == SavingsGoalKind.medium_term.value
        and g.target_date is not None
        and g.target_date <= cutoff
        and any(s.asset_id for s in active_sources(g))
    ]
    if not goals:
        return []
    positions = compute_holding_positions(db, user)
    values = cached_holding_values(db, user, positions, today)
    assets = {positions[k]["asset"].id: positions[k]["asset"] for k in values}
    exposures = resolve_exposures(db, user, list(assets.values()))
    # Cash sources dilute the risk: 9,000 on a deposit and 1,000 in an ETF is
    # a cautious goal, not an all-equity one.
    balances = {b.account_id: b.balance_base_currency for b in account_balances(db, user)}

    alerts: list[Alert] = []
    for goal in goals:
        total = Decimal("0")
        risky = Decimal("0")
        for source in active_sources(goal):
            if source.asset_id is None:
                total += max(Decimal("0"), balances.get(source.account_id, Decimal("0")))
                continue
            value = values.get((source.account_id, source.asset_id))
            if value is None:
                continue
            total += value
            weights = exposures.get(source.asset_id, {}).get("asset_class")
            if weights is not None:
                share = sum(
                    (weights.weights.get(c, Decimal("0")) for c in RISKY_ASSET_CLASSES),
                    Decimal("0"),
                )
                risky += value * share / 100
        if total > 0 and risky / total * 100 >= RISKY_SHARE:
            alerts.append(
                Alert(
                    id=f"goal_horizon:{goal.id}:{goal.target_date}",
                    kind="goal_horizon_mismatch",
                    tone=AlertTone.warn,
                    repeat=AlertRepeat.once,
                    label=goal.name,
                    due_date=goal.target_date,
                    percentage=round(float(risky / total * 100), 1),
                    link="/planning",
                )
            )
    return alerts


def _emergency_alerts(
    db: Session, user: User, pillars: PillarsResponse, today: date_, month: str
) -> list[Alert]:
    """Buying investments this month while the emergency fund is short."""
    emergency = next(p for p in pillars.pillars if p.key == PillarKey.emergency)
    short = [s for s in emergency.steps if s.target_amount is not None and not s.is_funded]
    if not short:
        return []
    bought = (
        db.query(AssetTransaction.id)
        .join(Account, Account.id == AssetTransaction.account_id)
        .filter(
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
            AssetTransaction.deleted_at.is_(None),
            AssetTransaction.type == "buy",
            AssetTransaction.date >= month_start(today),
            AssetTransaction.date <= today,
        )
        .first()
    )
    if bought is None:
        return []
    return [
        Alert(
            id=f"invest_no_emergency:{month}",
            kind="investing_without_emergency_fund",
            tone=AlertTone.warn,
            repeat=AlertRepeat.once,
            label=short[0].name,
            amount=emergency.gap,
            currency=pillars.base_currency,
            link="/planning",
        )
    ]


def _rule_alerts(
    db: Session, user: User, pillars: PillarsResponse, today: date_, month: str
) -> list[Alert]:
    status = evaluate(db, user, today, pillars=pillars)
    kinds = {
        PortfolioRuleKind.target.value: "allocation_out_of_band",
        PortfolioRuleKind.max_share.value: "allocation_over_cap",
        PortfolioRuleKind.excess_cash.value: "excess_cash",
        PortfolioRuleKind.min_invested.value: "below_min_invested_share",
    }
    alerts: list[Alert] = []
    for item in status.rules:
        if item.state in (RuleState.ok, RuleState.unknown):
            continue
        rule = item.rule
        limit = (
            rule.target_pct
            if rule.kind == PortfolioRuleKind.target
            else rule.max_pct
            if rule.kind == PortfolioRuleKind.max_share
            else rule.min_pct
        )
        alerts.append(
            Alert(
                id=f"rule:{rule.id}:{item.state.value}:{month}",
                kind=kinds[rule.kind.value],
                tone=AlertTone.warn,
                repeat=AlertRepeat.once,
                label=item.label or (rule.bucket or ""),
                amount=item.actual_amount,
                currency=status.base_currency,
                committed=item.limit_amount,
                percentage=item.actual_pct,
                limit_percentage=float(limit) if limit is not None else None,
                dimension=rule.dimension,
                bucket=rule.bucket,
                link="/planning",
            )
        )
    return alerts


def _stale_alerts(db: Session, user: User, today: date_) -> list[Alert]:
    result = allocation(db, user, ExposureDimension.region, today)
    if result.stale_count == 0:
        return []
    return [
        Alert(
            id=f"exposure_stale:{today.year}",
            kind="exposure_data_stale",
            tone=AlertTone.warn,
            repeat=AlertRepeat.once,
            label=str(result.stale_count),
            link="/portfolio",
        )
    ]
