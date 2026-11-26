"""
Guardrails on pillar 4, and what they say right now.

The rules are the user's. Presets only fill in asset-class/region targets
from a few generic textbook mixes, expressed as weights and never as
products, and nothing is preset as a cap: "at most 50% in one country"
would fire on a plain all-world fund (about 63% US), and a rule that fires
on the textbook portfolio only teaches the user to ignore it. Wording stays
"the limit you set", never "you should buy".

**Idle cash** and **invested share** read the same quantity, so they can't
contradict each other: idle cash is what the operating accounts hold above
pillar 1's target and the debits scheduled from them, less what the cascade
would send to the tax provision, the emergency fund and the goals with a
target, plus cash sitting on investment accounts; the invested share is
pillar 4 over pillar 4 plus that idle cash. The tax provision, the dated
goals and the emergency fund are never in either — "too little invested"
must not mean "invest the money for the F24".

A rule on a dimension that is less than 90% classified is `unknown`, not
judged: a band computed on half the portfolio is a confident wrong number.

The rebalancing suggestion splits new money only. Selling to rebalance
realises gains (26%, 12.5% on government bonds) and ETF losses can't offset
ETF gains, so it is never suggested.
"""

from collections import defaultdict
from datetime import date as date_
from decimal import ROUND_DOWN, Decimal

from sqlalchemy.orm import Session

from app.models import PortfolioRule, User
from app.schemas import (
    ContributionSplit,
    ExposureDimension,
    PillarKey,
    PillarsResponse,
    PortfolioAllocation,
    PortfolioPreset,
    PortfolioRuleKind,
    PortfolioRulesStatus,
    PortfolioRuleStatus,
    PresetTarget,
    RuleState,
    TargetMode,
)
from app.schemas import PortfolioRule as PortfolioRuleSchema
from app.services.operating_cash import operating_cash
from app.services.pillars import build_pillars
from app.services.portfolio_allocation import MIN_COVERAGE, allocation

HUNDRED = Decimal("100")


def _preset(key: str, label: str, description: str, targets: dict[str, dict[str, str]]):
    return PortfolioPreset(
        key=key,
        label=label,
        description=description,
        targets=[
            PresetTarget(dimension=ExposureDimension(dim), bucket=b, target_pct=Decimal(v))
            for dim, buckets in targets.items()
            for b, v in buckets.items()
        ],
    )


# Generic mixes, not recommendations: none is suggested over another, and
# none names a product.
PRESETS: list[PortfolioPreset] = [
    _preset(
        "all_world",
        "Tutto il mondo",
        "Solo azioni, pesate come il mercato globale (circa i pesi dell'MSCI ACWI).",
        {
            "asset_class": {"equity": "100"},
            "region": {
                "north_america": "65",
                "europe_ex_italy": "11",
                "italy": "1",
                "united_kingdom": "3",
                "japan": "5",
                "pacific_ex_japan": "3",
                "emerging": "12",
            },
        },
    ),
    _preset(
        "usa_only",
        "Solo USA",
        "Solo azioni statunitensi: un solo mercato, quindi più concentrato.",
        {"asset_class": {"equity": "100"}, "region": {"north_america": "100"}},
    ),
    _preset(
        "80_20",
        "80/20",
        "80% azioni, 20% obbligazioni.",
        {"asset_class": {"equity": "80", "bond": "20"}},
    ),
    _preset(
        "60_40",
        "60/40",
        "60% azioni, 40% obbligazioni: il bilanciato classico.",
        {"asset_class": {"equity": "60", "bond": "40"}},
    ),
    _preset(
        "30_70",
        "30/70",
        "30% azioni, 70% obbligazioni: prudente.",
        {"asset_class": {"equity": "30", "bond": "70"}},
    ),
]
PRESETS_BY_KEY = {p.key: p for p in PRESETS}


def list_rules(db: Session, user: User) -> list[PortfolioRule]:
    return (
        db.query(PortfolioRule)
        .filter(PortfolioRule.user_id == user.id)
        .order_by(PortfolioRule.kind, PortfolioRule.dimension, PortfolioRule.created_at)
        .all()
    )


def idle_cash(db: Session, user: User, pillars: PillarsResponse, on_date: date_) -> Decimal | None:
    """
    What the cascade would find no job for: pillar 1's surplus (already net
    of the debits scheduled from those accounts) less the tax provision's gap
    and the gaps of the emergency fund and of every goal with a target, plus
    the cash idling on investment accounts. Built on the same figures as the
    waterfall, so "idle" here is never money the cascade is about to send
    to the F24s or to the car.
    """
    surplus = operating_cash(db, user, on_date).surplus
    if surplus is None:
        return None
    by_key = {p.key: p for p in pillars.pillars}
    needs = Decimal("0")
    for key in (PillarKey.emergency, PillarKey.planned):
        pillar = by_key[key]
        needs += sum((st.gap for st in pillar.steps if st.target_amount is not None), Decimal("0"))
        for item in pillar.items:
            if item.kind.value == "tax_provision" and item.amount is not None:
                needs += max(Decimal("0"), item.amount - (item.available or Decimal("0")))
    broker_cash = sum(
        (
            i.available or Decimal("0")
            for i in by_key[PillarKey.investing].items
            if i.kind.value == "uninvested_cash" and i.currency == user.base_currency
        ),
        Decimal("0"),
    )
    # Goal accounts' money beyond every goal they fund is free too.
    excess = sum(
        (
            i.available or Decimal("0")
            for i in by_key[PillarKey.operating].items
            if i.kind.value == "goal_account_excess"
        ),
        Decimal("0"),
    )
    return max(Decimal("0"), surplus + excess - needs) + max(Decimal("0"), broker_cash)


def _open_ended_contribution(pillars: PillarsResponse) -> Decimal:
    investing = next(p for p in pillars.pillars if p.key == PillarKey.investing)
    return sum(
        (s.allocated_amount for s in investing.steps if s.target_mode == TargetMode.open_ended),
        Decimal("0"),
    )


def split_contribution(
    alloc: PortfolioAllocation, targets: dict[str, Decimal], amount: Decimal
) -> list[ContributionSplit]:
    """
    New money toward the targets: each bucket's shortfall against its target
    on the *enlarged* portfolio, filled proportionally when the money isn't
    enough, and any surplus spread by the targets themselves.
    """
    if amount <= 0 or not targets:
        return []
    current = {b.bucket: b.value for b in alloc.buckets}
    total_after = alloc.total + amount
    shortfall = {
        bucket: max(Decimal("0"), total_after * pct / HUNDRED - current.get(bucket, Decimal("0")))
        for bucket, pct in targets.items()
    }
    gap = sum(shortfall.values(), Decimal("0"))
    split: dict[str, Decimal] = defaultdict(Decimal)
    if gap >= amount and gap > 0:
        for bucket, need in shortfall.items():
            split[bucket] += amount * need / gap
    else:
        rest = amount - gap
        weight = sum(targets.values(), Decimal("0"))
        for bucket, need in shortfall.items():
            split[bucket] += need + (rest * targets[bucket] / weight if weight else 0)
    return [
        ContributionSplit(bucket=b, amount=v.quantize(Decimal("0.01"), rounding=ROUND_DOWN))
        for b, v in sorted(split.items(), key=lambda kv: -kv[1])
        if v >= Decimal("0.01")
    ]


def evaluate(
    db: Session,
    user: User,
    on_date: date_,
    *,
    pillars: PillarsResponse | None = None,
) -> PortfolioRulesStatus:
    """Cache-only, like everything the alerts banner calls."""
    rules = list_rules(db, user)
    pillars = pillars or build_pillars(db, user, on_date)
    allocations: dict[ExposureDimension, PortfolioAllocation] = {}

    def alloc(dimension: ExposureDimension) -> PortfolioAllocation:
        if dimension not in allocations:
            allocations[dimension] = allocation(db, user, dimension, on_date)
        return allocations[dimension]

    invested = alloc(ExposureDimension.asset_class).total
    idle = idle_cash(db, user, pillars, on_date)
    share = (
        round(float(invested / (invested + idle) * 100), 1)
        if idle is not None and invested + idle > 0
        else None
    )

    statuses: list[PortfolioRuleStatus] = []
    for rule in rules:
        statuses.append(_judge(rule, alloc, invested, idle, share, pillars))

    targets = {
        r.bucket: Decimal(str(r.target_pct))
        for r in rules
        if r.kind == PortfolioRuleKind.target.value
        and r.dimension == ExposureDimension.asset_class.value
        and r.bucket
    }
    contribution = _open_ended_contribution(pillars)
    return PortfolioRulesStatus(
        base_currency=user.base_currency,
        rules=statuses,
        idle_cash=idle.quantize(Decimal("0.01")) if idle is not None else None,
        invested=invested,
        invested_share=share,
        contribution=contribution,
        contribution_split=split_contribution(
            alloc(ExposureDimension.asset_class), targets, contribution
        )
        if targets
        else [],
    )


def _judge(rule, alloc, invested, idle, share, pillars) -> PortfolioRuleStatus:
    schema = PortfolioRuleSchema.model_validate(rule)
    kind = PortfolioRuleKind(rule.kind)

    if kind in (PortfolioRuleKind.target, PortfolioRuleKind.max_share):
        if rule.dimension == "position":
            base = alloc(ExposureDimension.asset_class)
            if base.total == 0:
                return PortfolioRuleStatus(
                    rule=schema, state=RuleState.unknown, reason="nothing_invested"
                )
            value = sum(
                (
                    p.value or Decimal("0")
                    for p in base.positions
                    if p.asset is not None and str(p.asset.id) == rule.bucket
                ),
                Decimal("0"),
            )
            label = next(
                (
                    p.asset.symbol
                    for p in base.positions
                    if p.asset and str(p.asset.id) == rule.bucket
                ),
                None,
            )
            pct = float(value / base.total * 100)
            state = RuleState.over if pct > float(rule.max_pct) else RuleState.ok
            return PortfolioRuleStatus(
                rule=schema, state=state, actual_pct=round(pct, 1), actual_amount=value, label=label
            )

        result = alloc(ExposureDimension(rule.dimension))
        if result.total == 0:
            return PortfolioRuleStatus(
                rule=schema, state=RuleState.unknown, reason="nothing_invested"
            )
        if result.coverage < MIN_COVERAGE:
            return PortfolioRuleStatus(rule=schema, state=RuleState.unknown, reason="coverage")
        bucket = next((b for b in result.buckets if b.bucket == rule.bucket), None)
        pct = bucket.percentage if bucket else 0.0
        amount = bucket.value if bucket else Decimal("0")
        if kind == PortfolioRuleKind.target:
            target = float(rule.target_pct)
            tolerance = float(rule.tolerance_pct)
            state = (
                RuleState.over
                if pct > target + tolerance
                else RuleState.under
                if pct < target - tolerance
                else RuleState.ok
            )
        else:
            state = RuleState.over if pct > float(rule.max_pct) else RuleState.ok
        return PortfolioRuleStatus(rule=schema, state=state, actual_pct=pct, actual_amount=amount)

    if kind == PortfolioRuleKind.excess_cash:
        if idle is None:
            return PortfolioRuleStatus(rule=schema, state=RuleState.unknown, reason="no_history")
        if rule.threshold_amount is not None:
            limit = Decimal(str(rule.threshold_amount))
        else:
            spend = pillars.monthly_total_expenses
            if spend is None:
                return PortfolioRuleStatus(
                    rule=schema, state=RuleState.unknown, reason="no_history"
                )
            limit = (spend * Decimal(str(rule.threshold_months))).quantize(Decimal("0.01"))
        state = RuleState.over if idle > limit else RuleState.ok
        return PortfolioRuleStatus(
            rule=schema,
            state=state,
            actual_amount=idle.quantize(Decimal("0.01")),
            limit_amount=limit,
        )

    # min_invested
    if share is None:
        return PortfolioRuleStatus(rule=schema, state=RuleState.unknown, reason="no_history")
    state = RuleState.under if share < float(rule.min_pct) else RuleState.ok
    return PortfolioRuleStatus(rule=schema, state=state, actual_pct=share, actual_amount=invested)
