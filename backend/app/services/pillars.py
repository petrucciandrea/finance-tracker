"""
The plan's four pillars: where the money is, against what each layer needs.

1. **Operating cash** — the accounts nothing else claims (current accounts,
   savings, cash, cards). Target: `operating_cash_months` × the average
   monthly spend, unknown until there is a complete month of history.
2. **Emergency fund** — the `emergency_fund` goals.
3. **Planned expenses** — the `medium_term` goals (dated or not), plus what
   other sections already put aside or will ask for: the P.IVA tax
   provision against what the F24s will still want, and vehicle deadlines
   with an amount, each with the monthly share that would cover it.
4. **Investing** — the `long_term` goals, plus the cash on investment
   accounts and the holdings that no goal and no provision claims.

Built on `compute_waterfall`, so a goal reads the same here as in the
cascade, and like it this module never calls out: holdings and conversions
use the caches only (see `net_worth.cached_holding_values`).

Vehicle deadlines count in `monthly_required` but not in the pillar's
target/current: nothing records where their money sits (they are paid from
the operating accounts), and a gap that can never close would only teach
the user to ignore it.
"""

from datetime import date as date_
from decimal import ROUND_UP, Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Account, User
from app.schemas import (
    AccountType,
    Pillar,
    PillarItem,
    PillarItemKind,
    PillarKey,
    PillarsResponse,
    SavingsGoalKind,
    WaterfallStep,
)
from app.services import alerts as alerts_service
from app.services import flat_rate
from app.services.net_worth import (
    account_balances,
    cached_holding_values,
    compute_holding_positions,
    latest_cached_rate,
)
from app.services.operating_cash import operating_cash
from app.services.periods import month_start, months_between
from app.services.waterfall import active_sources, compute_waterfall, list_goals

# Accounts whose unclaimed cash is pillar 4's "to be invested" rather than
# pillar 1's spending money.
INVESTMENT_ACCOUNT_TYPES = {AccountType.investment.value, AccountType.crypto_wallet.value}

PILLAR_OF_KIND = {
    SavingsGoalKind.emergency_fund.value: PillarKey.emergency,
    SavingsGoalKind.medium_term.value: PillarKey.planned,
    SavingsGoalKind.long_term.value: PillarKey.investing,
}


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _monthly_share(amount: Decimal, due: date_, period_start: date_) -> Decimal:
    """amount / contributions left, this month included; all of it once due."""
    due_month = month_start(due)
    months = months_between(period_start, due_month) + 1 if due_month >= period_start else 1
    return (amount / months).quantize(Decimal("0.01"), rounding=ROUND_UP)


def build_pillars(db: Session, user: User, on_date: date_) -> PillarsResponse:
    waterfall = compute_waterfall(db, user, on_date)
    period_start = waterfall.period_start
    base = user.base_currency

    goals = list_goals(db, user, include_completed=False)
    claimed_cash: set[UUID] = set()
    claimed_holdings: set[tuple[UUID, UUID]] = set()
    for goal in goals:
        for source in active_sources(goal):
            if source.asset_id is None:
                claimed_cash.add(source.account_id)
            else:
                claimed_holdings.add((source.account_id, source.asset_id))
    provision_sources = flat_rate.active_sources(db, user)
    provision_cash = {s.account_id for s in provision_sources if s.asset_id is None}
    provision_holdings = {
        (s.account_id, s.asset_id) for s in provision_sources if s.asset_id is not None
    }

    accounts = {
        a.id: a
        for a in db.query(Account).filter(Account.user_id == user.id, Account.deleted_at.is_(None))
    }
    positions = compute_holding_positions(db, user)
    # Stocks are valued today whatever day was asked for, like the balances
    # (see compute_waterfall).
    now = date_.today()
    holding_values = cached_holding_values(db, user, positions, now)
    has_unpriced = any(v is None for v in holding_values.values())

    # --- Pillar 1 and pillar 4's idle cash -------------------------------
    uninvested: list[PillarItem] = []
    for balance in account_balances(db, user):
        if balance.account_id in claimed_cash or balance.account_id in provision_cash:
            continue
        account = accounts.get(balance.account_id)
        if account is None:
            continue
        if account.type in INVESTMENT_ACCOUNT_TYPES:
            if balance.balance_base_currency != 0:
                uninvested.append(
                    PillarItem(
                        kind=PillarItemKind.uninvested_cash,
                        label=account.name,
                        available=_money(balance.balance_base_currency),
                        currency=base,
                        account_name=account.name,
                    )
                )

    # Same figures the waterfall's surplus is computed from.
    op = operating_cash(db, user, now)
    operating = op.current
    monthly_spend = op.monthly_spend
    months = op.months
    operating_target = op.target

    # --- Pillar 3's items -------------------------------------------------
    planned_items: list[PillarItem] = []
    ledger = flat_rate.load_ledger(db, user)
    if not ledger.is_empty() or provision_sources:
        eur_rate = latest_cached_rate(db, flat_rate.CURRENCY, base, now)
        requirement = flat_rate.cash_requirement(ledger, now)
        provision = sum(
            (
                b.balance_base_currency
                for b in account_balances(db, user)
                if b.account_id in provision_cash
            ),
            Decimal("0"),
        )
        unpriced_provision = False
        for key in provision_holdings:
            value = holding_values.get(key)
            if value is None:
                unpriced_provision = unpriced_provision or key in holding_values
            else:
                provision += value
        has_unpriced = has_unpriced or unpriced_provision
        if eur_rate is not None:
            planned_items.append(
                PillarItem(
                    kind=PillarItemKind.tax_provision,
                    label="Accantonamento tasse P.IVA",
                    amount=_money(requirement * eur_rate),
                    available=_money(provision),
                    currency=base,
                )
            )

    for deadline, vehicle in alerts_service.open_vehicle_deadlines(db, user):
        if deadline.amount is None:
            continue
        amount = Decimal(str(deadline.amount))
        planned_items.append(
            PillarItem(
                kind=PillarItemKind.vehicle_deadline,
                label=alerts_service.vehicle_deadline_label(
                    vehicle.name, deadline.kind, deadline.label
                ),
                amount=amount,
                currency=deadline.currency,
                due_date=deadline.due_date,
                monthly=_monthly_share(amount, deadline.due_date, period_start),
                account_name=(
                    accounts[deadline.account_id].name if deadline.account_id in accounts else None
                ),
            )
        )

    # --- Pillar 4's free holdings ----------------------------------------
    free_value = Decimal("0")
    free_count = 0
    for key, value in holding_values.items():
        if key in claimed_holdings or key in provision_holdings or value is None:
            continue
        free_value += value
        free_count += 1
    investing_items = list(uninvested)
    if free_count:
        investing_items.insert(
            0,
            PillarItem(
                kind=PillarItemKind.free_holdings,
                label=f"Investimenti non assegnati ({free_count})",
                available=_money(free_value),
                currency=base,
            ),
        )

    # --- Assemble -----------------------------------------------------------
    steps_by_pillar: dict[PillarKey, list[WaterfallStep]] = {key: [] for key in PillarKey}
    for step in waterfall.steps:
        steps_by_pillar[PILLAR_OF_KIND[step.kind.value]].append(step)

    def from_steps(key: PillarKey, items: list[PillarItem]) -> Pillar:
        steps = steps_by_pillar[key]
        targets = [s.target_amount for s in steps if s.target_amount is not None]
        current = sum((s.current_amount for s in steps), Decimal("0"))
        # Items in another currency (a vehicle deadline in CHF) stay out of
        # the sums rather than being added unconverted.
        target = sum(targets, Decimal("0"))
        has_target = bool(targets)
        for item in items:
            if item.available is not None and item.currency == base:
                current += item.available
                if item.amount is not None:
                    target += item.amount
                    has_target = True
        monthly = [s.required_monthly for s in steps if s.required_monthly is not None]
        monthly += [i.monthly for i in items if i.monthly is not None and i.currency == base]
        return Pillar(
            key=key,
            target=_money(target) if has_target else None,
            current=_money(current),
            gap=_money(max(Decimal("0"), target - current)) if has_target else None,
            monthly_required=_money(sum(monthly, Decimal("0"))) if monthly else None,
            steps=steps,
            items=items,
        )

    pillars = [
        Pillar(
            key=PillarKey.operating,
            target=operating_target,
            current=_money(operating),
            gap=(
                _money(max(Decimal("0"), operating_target - operating))
                if operating_target is not None
                else None
            ),
            steps=[],
            # Not in `current`: that is the spending accounts. Shown because
            # the cascade moves it, from those accounts.
            items=[
                PillarItem(
                    kind=PillarItemKind.goal_account_excess,
                    label=f"Eccedenza su {e.account_name}",
                    available=e.amount,
                    currency=base,
                    account_name=e.account_name,
                )
                for e in waterfall.goal_account_excesses
            ],
        ),
        from_steps(PillarKey.emergency, []),
        from_steps(PillarKey.planned, planned_items),
        from_steps(PillarKey.investing, investing_items),
    ]
    # Pillar 4 has no ceiling: an open-ended rung or a free holding is "more
    # is fine", so a target there would only be the sum of whatever fixed
    # long-term goals happen to exist. Kept only when every step has one.
    investing = pillars[3]
    if any(s.target_amount is None for s in investing.steps) or not investing.steps:
        investing.target = None
        investing.gap = None

    return PillarsResponse(
        base_currency=base,
        period_start=period_start,
        operating_cash_months=months,
        monthly_total_expenses=monthly_spend,
        has_unpriced_holdings=has_unpriced or any(s.has_unpriced_sources for s in waterfall.steps),
        pillars=pillars,
    )
