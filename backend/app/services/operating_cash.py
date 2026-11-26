"""
Pillar 1, the operating cash: one definition for the pillars view, the
waterfall and the portfolio rules, which all need "how much is on the
spending accounts beyond what the month needs".

- **Operating accounts** are the ones nothing else claims: not a goal's cash
  source, not the tax provision, and not an investment or crypto account
  (their idle cash is pillar 4's "to be invested").
- **Target** = `operating_cash_months` × average total monthly spend; None
  without a complete month of history.
- **Surplus** = balance − target − what's scheduled to leave those accounts
  (F24 direct debits, vehicle deadlines with an amount). None when the
  target is unknown: "everything above zero is surplus" would sweep the
  rent into the emergency fund.
"""

from dataclasses import dataclass
from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Account, SavingsGoal, SavingsGoalSource, User
from app.schemas import AccountType
from app.services import alerts as alerts_service
from app.services import flat_rate
from app.services.net_worth import account_balances
from app.services.planning import average_monthly_total_expenses, get_or_create_plan

INVESTMENT_ACCOUNT_TYPES = {AccountType.investment.value, AccountType.crypto_wallet.value}


def claimed_cash_accounts(db: Session, user: User) -> set[UUID]:
    """Accounts whose cash funds a live goal (a reached goal's sources are retired)."""
    rows = (
        db.query(SavingsGoalSource.account_id)
        .join(SavingsGoal, SavingsGoal.id == SavingsGoalSource.goal_id)
        .filter(
            SavingsGoal.user_id == user.id,
            SavingsGoal.deleted_at.is_(None),
            SavingsGoal.completed_at.is_(None),
            SavingsGoalSource.deleted_at.is_(None),
            SavingsGoalSource.asset_id.is_(None),
        )
        .all()
    )
    return {r[0] for r in rows}


@dataclass
class OperatingCash:
    current: Decimal
    target: Decimal | None
    committed: Decimal
    surplus: Decimal | None
    monthly_spend: Decimal | None
    months: Decimal
    # Base-currency balance per operating account, largest first.
    accounts: list[tuple[Account, Decimal]]


def operating_cash(db: Session, user: User, on_date: date_) -> OperatingCash:
    plan = get_or_create_plan(db, user)
    claimed = claimed_cash_accounts(db, user)
    provision = {s.account_id for s in flat_rate.active_sources(db, user) if s.asset_id is None}
    accounts = {
        a.id: a
        for a in db.query(Account).filter(Account.user_id == user.id, Account.deleted_at.is_(None))
    }

    rows: list[tuple[Account, Decimal]] = []
    for balance in account_balances(db, user):
        account = accounts.get(balance.account_id)
        if (
            account is None
            or account.id in claimed
            or account.id in provision
            or account.type in INVESTMENT_ACCOUNT_TYPES
        ):
            continue
        rows.append((account, balance.balance_base_currency))
    rows.sort(key=lambda r: -r[1])
    operating_ids: set[UUID] = {a.id for a, _ in rows}
    current = sum((b for _, b in rows), Decimal("0"))

    committed = Decimal("0")
    scheduled = alerts_service.scheduled_payments(db, user)
    deadlines = alerts_service.open_vehicle_deadlines(db, user)
    for c in alerts_service.commitments(db, user, scheduled, deadlines):
        # Only what leaves the operating accounts, in the base currency (a
        # CHF deadline stays out rather than being added unconverted).
        if c.account_id in operating_ids and c.currency == user.base_currency:
            committed += c.committed

    months = Decimal(str(plan.operating_cash_months))
    monthly_spend = average_monthly_total_expenses(
        db, user, as_of=on_date, lookback_months=plan.lookback_months
    )
    target = (
        (monthly_spend * months).quantize(Decimal("0.01")) if monthly_spend is not None else None
    )
    surplus = max(Decimal("0"), current - target - committed) if target is not None else None
    return OperatingCash(
        current=current,
        target=target,
        committed=committed,
        surplus=surplus,
        monthly_spend=monthly_spend,
        months=months,
        accounts=rows,
    )
