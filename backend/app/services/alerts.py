"""
What needs attention, computed on every read (there is no scheduler to push
anything, so the app checks when it is opened):

- accounts that something is due from — scheduled F24s, vehicle deadlines
  with an amount and an account — whose balance doesn't cover it, or covers
  it by less than a margin (the larger of 15 and 20% of what's due);
- F24 lines due within two weeks, or already past, with nothing paid or
  scheduled against them;
- scheduled payments whose date has passed without being confirmed;
- vehicle deadlines due within two weeks, or already past.

A balance is only what the app knows: if the bank statement hasn't been
imported for a while it is stale, which is why each commitment carries the
date of the account's latest movement.
"""

from collections import defaultdict
from datetime import date as date_
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Account, PhysicalAsset, TaxPayment, Transaction, User, VehicleDeadline
from app.schemas import (
    AccountCommitment,
    Alert,
    AlertRepeat,
    AlertsResponse,
    AlertTone,
    CommitmentItem,
)
from app.services import flat_rate
from app.services.net_worth import account_balances

LEAD_DAYS = 14
MARGIN_MINIMUM = Decimal("15")
MARGIN_SHARE = Decimal("0.20")

VEHICLE_DEADLINE_LABELS = {
    "insurance": "assicurazione",
    "road_tax": "bollo auto",
    "inspection": "revisione",
    "service": "tagliando",
}


def margin_for(committed: Decimal) -> Decimal:
    return max(MARGIN_MINIMUM, flat_rate.money(committed * MARGIN_SHARE))


def vehicle_deadline_label(vehicle_name: str, kind: str, label: str | None) -> str:
    what = label if label else VEHICLE_DEADLINE_LABELS.get(kind, kind)
    if label and kind in VEHICLE_DEADLINE_LABELS:
        what = f"{VEHICLE_DEADLINE_LABELS[kind]} ({label})"
    return f"{vehicle_name} · {what}"


def open_vehicle_deadlines(db: Session, user: User) -> list[tuple[VehicleDeadline, PhysicalAsset]]:
    rows = (
        db.query(VehicleDeadline, PhysicalAsset)
        .join(PhysicalAsset, PhysicalAsset.id == VehicleDeadline.physical_asset_id)
        .filter(
            VehicleDeadline.user_id == user.id,
            VehicleDeadline.deleted_at.is_(None),
            VehicleDeadline.done_on.is_(None),
            PhysicalAsset.deleted_at.is_(None),
            # A sold vehicle's renewals are the buyer's.
            PhysicalAsset.sold_at.is_(None),
        )
        .order_by(VehicleDeadline.due_date)
        .all()
    )
    return [(d, v) for d, v in rows]


def scheduled_payments(db: Session, user: User) -> list[TaxPayment]:
    return (
        db.query(TaxPayment)
        .filter(
            TaxPayment.user_id == user.id,
            TaxPayment.deleted_at.is_(None),
            TaxPayment.status == "scheduled",
        )
        .order_by(TaxPayment.paid_on)
        .all()
    )


def commitments(
    db: Session,
    user: User,
    scheduled: list[TaxPayment],
    deadlines: list[tuple[VehicleDeadline, PhysicalAsset]],
) -> list[AccountCommitment]:
    items: dict[UUID, list[CommitmentItem]] = defaultdict(list)
    for payment in scheduled:
        if payment.account_id is None:
            continue
        items[payment.account_id].append(
            CommitmentItem(
                label="F24 "
                + flat_rate.payment_label(payment.component, payment.kind, payment.fiscal_year),
                due_date=payment.paid_on,
                amount=Decimal(payment.amount),
            )
        )
    for deadline, vehicle in deadlines:
        if deadline.account_id is None or deadline.amount is None:
            continue
        items[deadline.account_id].append(
            CommitmentItem(
                label=vehicle_deadline_label(vehicle.name, deadline.kind, deadline.label),
                due_date=deadline.due_date,
                amount=Decimal(deadline.amount),
            )
        )
    if not items:
        return []

    accounts = {
        a.id: a
        for a in db.query(Account).filter(
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
            Account.id.in_(list(items)),
        )
    }
    balances = {b.account_id: Decimal(b.balance) for b in account_balances(db, user)}
    last_movement = dict(
        db.query(Transaction.account_id, func.max(Transaction.date))
        .filter(Transaction.account_id.in_(list(accounts)), Transaction.deleted_at.is_(None))
        .group_by(Transaction.account_id)
        .all()
    )

    result: list[AccountCommitment] = []
    for account_id, rows in items.items():
        account = accounts.get(account_id)
        if account is None:
            continue
        rows.sort(key=lambda r: r.due_date)
        committed = sum((r.amount for r in rows), Decimal("0"))
        margin = margin_for(committed)
        result.append(
            AccountCommitment(
                account_id=account.id,
                account_name=account.name,
                currency=account.currency,
                balance=balances.get(account.id, Decimal("0")),
                committed=committed,
                margin=margin,
                threshold=committed + margin,
                last_movement_on=last_movement.get(account.id),
                items=rows,
            )
        )
    result.sort(key=lambda c: c.items[0].due_date)
    return result


def _account_alert(
    c: AccountCommitment, *, id_: str, kind: str, tone: AlertTone, repeat: AlertRepeat
) -> Alert:
    first = c.items[0]
    return Alert(
        id=id_,
        kind=kind,
        tone=tone,
        repeat=repeat,
        label=first.label,
        due_date=first.due_date,
        amount=first.amount,
        currency=c.currency,
        account_id=c.account_id,
        account_name=c.account_name,
        balance=c.balance,
        committed=c.committed,
        margin=c.margin,
        link="/accounts",
    )


def _account_alerts(commitments_: list[AccountCommitment]) -> list[Alert]:
    alerts: list[Alert] = []
    for c in commitments_:
        if c.balance < c.committed:
            alerts.append(
                _account_alert(
                    c,
                    id_=f"account-short:{c.account_id}",
                    kind="account_short",
                    tone=AlertTone.danger,
                    repeat=AlertRepeat.every_visit,
                )
            )
        elif c.balance < c.threshold:
            # Remembered per commitment: a new debit on the account is a new warning.
            alerts.append(
                _account_alert(
                    c,
                    id_=f"account-near:{c.account_id}:{c.committed}",
                    kind="account_near",
                    tone=AlertTone.warn,
                    repeat=AlertRepeat.once,
                )
            )
    return alerts


def _f24_alerts(db: Session, user: User, today: date_) -> list[Alert]:
    ledger = flat_rate.load_ledger(db, user)
    if ledger.is_empty():
        return []
    horizon = today + timedelta(days=LEAD_DAYS)
    # Last year's too: a deadline missed in December is still missed in January.
    lines = [
        d
        for d in flat_rate.deadlines_in(ledger, (today.year - 1, today.year, today.year + 1), today)
        if d.amount_due > 0 and not d.is_arranged and d.due_date <= horizon
    ]
    by_date: dict[date_, list[flat_rate.Deadline]] = defaultdict(list)
    for line in lines:
        by_date[line.due_date].append(line)

    alerts: list[Alert] = []
    for due_date, rows in sorted(by_date.items()):
        overdue = due_date < today
        alerts.append(
            Alert(
                id=f"f24:{due_date.isoformat()}",
                kind="f24_overdue" if overdue else "f24_upcoming",
                tone=AlertTone.danger if overdue else AlertTone.warn,
                repeat=AlertRepeat.every_visit,
                label="; ".join(
                    flat_rate.payment_label(r.component, r.kind, r.fiscal_year) for r in rows
                ),
                due_date=due_date,
                amount=sum((r.amount_due for r in rows), Decimal("0")),
                currency=flat_rate.CURRENCY,
                link="/invoices",
            )
        )
    return alerts


def _unconfirmed_alerts(
    scheduled: list[TaxPayment], names: dict[UUID, str], today: date_
) -> list[Alert]:
    return [
        Alert(
            id=f"scheduled:{p.id}:{p.paid_on.isoformat()}",
            kind="scheduled_unconfirmed",
            tone=AlertTone.warn,
            repeat=AlertRepeat.every_visit,
            label=f"F24 {flat_rate.payment_label(p.component, p.kind, p.fiscal_year)}",
            due_date=p.paid_on,
            amount=Decimal(p.amount),
            currency=flat_rate.CURRENCY,
            account_id=p.account_id,
            account_name=names.get(p.account_id) if p.account_id else None,
            link="/invoices",
        )
        for p in scheduled
        if p.paid_on < today
    ]


def _vehicle_alerts(
    deadlines: list[tuple[VehicleDeadline, PhysicalAsset]], today: date_
) -> list[Alert]:
    horizon = today + timedelta(days=LEAD_DAYS)
    alerts: list[Alert] = []
    for deadline, vehicle in deadlines:
        if deadline.due_date > horizon:
            continue
        overdue = deadline.due_date < today
        alerts.append(
            Alert(
                id=f"vehicle:{deadline.id}:{deadline.due_date.isoformat()}",
                kind="vehicle_overdue" if overdue else "vehicle_upcoming",
                tone=AlertTone.danger if overdue else AlertTone.warn,
                repeat=AlertRepeat.every_visit,
                label=vehicle_deadline_label(vehicle.name, deadline.kind, deadline.label),
                due_date=deadline.due_date,
                amount=Decimal(deadline.amount) if deadline.amount is not None else None,
                currency=deadline.currency,
                account_id=deadline.account_id,
                link="/assets",
            )
        )
    return alerts


def build_alerts(db: Session, user: User, today: date_ | None = None) -> AlertsResponse:
    today = today or date_.today()
    scheduled = scheduled_payments(db, user)
    deadlines = open_vehicle_deadlines(db, user)
    commitments_ = commitments(db, user, scheduled, deadlines)
    names = {c.account_id: c.account_name for c in commitments_}

    # Imported here: plan_alerts builds on the pillars and the portfolio
    # rules, which themselves read this module's commitments.
    from app.services.plan_alerts import plan_alerts

    alerts = [
        *_account_alerts(commitments_),
        *_f24_alerts(db, user, today),
        *_unconfirmed_alerts(scheduled, names, today),
        *_vehicle_alerts(deadlines, today),
        *plan_alerts(db, user, today),
    ]
    alerts.sort(key=lambda a: (a.tone != AlertTone.danger, a.due_date or today))
    return AlertsResponse(alerts=alerts, commitments=commitments_)
