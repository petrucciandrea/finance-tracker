"""
Credits: spend fronted for other people.

An expense can say how much of it was `lent_amount`, i.e. paid on behalf of
others (a dinner on your card, friends hand back cash). Two consequences, kept
here so they can't drift apart:

- The spend counts only the user's own share, *immediately* and in the month of
  the expense. Waiting for the money to come back would rewrite closed months.
- What hasn't come back yet is a credit — an asset in net worth, never in cash
  (it doesn't extend the survival budget's runway or fund a waterfall rung).

When the money arrives it is an `income` with `repays_transaction_id` pointing
at the expense. It moves cash and closes the credit; it is not income, so every
income aggregate leaves it out.
"""

from dataclasses import dataclass, field
from datetime import date as date_
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.models import Account, Transaction, User
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate
from app.services.ownership import (
    ensure_account_open_on,
    get_or_create_misc_category,
    get_or_create_refunds_category,
    get_owned_leaf_category,
)


def net_expense_base() -> Any:
    """
    SQL expression: an expense's `amount_base_currency` minus the share fronted
    for others. Same frozen rate as the full amount — the share is a fraction
    of the same conversion — so nothing here ever reads a live rate.

    Use it wherever expense spend is summed. For a row with no `lent_amount`
    it is exactly `amount_base_currency`; the COALESCE only guards a zero
    amount, where the fraction would divide by zero.
    """
    amount = func.abs(Transaction.amount)
    own_share = amount - func.coalesce(Transaction.lent_amount, 0)
    return func.coalesce(
        Transaction.amount_base_currency * own_share / func.nullif(amount, 0),
        Transaction.amount_base_currency,
    )


def repaid_by_expense(db: Session, expense_ids: list[UUID]) -> dict[UUID, Decimal]:
    """What live repayments have brought back so far, per expense."""
    if not expense_ids:
        return {}
    rows = (
        db.query(Transaction.repays_transaction_id, func.sum(Transaction.amount))
        .filter(
            Transaction.repays_transaction_id.in_(expense_ids),
            Transaction.deleted_at.is_(None),
        )
        .group_by(Transaction.repays_transaction_id)
        .all()
    )
    return {row[0]: Decimal(str(row[1])) for row in rows if row[0] is not None}


def attach_repaid(db: Session, transactions: list[Transaction]) -> None:
    """
    Fill `repaid_amount` on the expenses in a response, in one query for the
    whole page. It is not a column, so it is set on the instance; every
    response containing an expense must go through here, or a value left by an
    earlier request in the same session would be served stale.
    """
    lent = [t for t in transactions if t.lent_amount is not None]
    repaid = repaid_by_expense(db, [t.id for t in lent])
    for transaction in transactions:
        value = (
            repaid.get(transaction.id, Decimal("0"))
            if transaction.lent_amount is not None
            else None
        )
        setattr(transaction, "repaid_amount", value)  # noqa: B010 — see docstring


def open_credit_expenses(db: Session, user: User) -> list[Transaction]:
    """Expenses that still have money to come back, oldest first."""
    expenses = (
        db.query(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.type == "expense",
            Transaction.lent_amount.isnot(None),
        )
        .order_by(Transaction.date.desc())
        .all()
    )
    repaid = repaid_by_expense(db, [t.id for t in expenses])
    open_ones = [
        t
        for t in expenses
        if t.lent_amount is not None and t.lent_amount - repaid.get(t.id, Decimal("0")) > 0
    ]
    attach_repaid(db, open_ones)
    return open_ones


# ---------------------------------------------------------------------------
# Rules for writing
# ---------------------------------------------------------------------------

def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def validate_repayment(
    db: Session,
    user: User,
    *,
    expense_id: UUID,
    amount: Decimal,
    currency: str,
    on_date: date_,
    exclude_id: UUID | None = None,
) -> Transaction:
    """
    Check an income may repay `expense_id` and return that expense.

    Same currency only: the credit is valued with the expense's own frozen
    rate, and a repayment in another currency would need a second conversion
    to know how much of the credit it closes (same constraint as giroconti).
    `exclude_id` is the repayment being edited, so it isn't counted twice
    against the cap.
    """
    expense = (
        db.query(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Transaction.id == expense_id,
            Account.user_id == user.id,
            Transaction.deleted_at.is_(None),
        )
        .first()
    )
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.type != "expense" or expense.lent_amount is None:
        raise _unprocessable(
            "A repayment must point at an expense with an amount fronted for others"
        )
    if amount <= 0:
        raise _unprocessable("A repayment amount must be positive")
    if currency != expense.currency:
        raise _unprocessable(
            f"A repayment must be in the expense's currency ({expense.currency}, not {currency})"
        )
    if on_date < expense.date:
        raise _unprocessable("A repayment cannot be dated before the expense it pays back")

    query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.repays_transaction_id == expense.id,
        Transaction.deleted_at.is_(None),
    )
    if exclude_id is not None:
        query = query.filter(Transaction.id != exclude_id)
    already = Decimal(str(query.scalar()))
    if already + amount > expense.lent_amount:
        raise _unprocessable(
            f"Repayments would exceed the amount fronted ({expense.lent_amount}); "
            f"{expense.lent_amount - already} is still open"
        )
    return expense


def create_offset(
    db: Session,
    user: User,
    *,
    credit_expense_id: UUID,
    account: Account,
    amount: Decimal,
    on_date: date_,
    description: str | None,
    category_id: UUID | None,
    necessity_level_override: str | None,
) -> tuple[Transaction, Transaction]:
    """
    Settle part of a credit in kind and return (spend, repayment). Flushes but
    does not commit — the caller owns the transaction.

    The friend paid for something of the user's own instead of handing cash
    back: the user's share of that is a real spend, and it closes that much
    credit. Nothing moves in cash, so both legs go on one account at the same
    rate and cancel out exactly. The repayment is the usual one (same cap, same
    currency, "Rimborsi", not income); the spend is a plain expense with no
    `lent_amount`.
    """
    expense = validate_repayment(
        db,
        user,
        expense_id=credit_expense_id,
        amount=amount,
        currency=account.currency,
        on_date=on_date,
    )
    ensure_account_open_on(account, on_date)

    if category_id is not None:
        spend_category_id = get_owned_leaf_category(db, category_id, user, "expense").id
    else:
        spend_category_id = get_or_create_misc_category(db, user, "expense").id
    repayment_category_id = get_or_create_refunds_category(db, user).id

    # Resolved before the first db.add(): a cache miss must not leave one leg.
    try:
        rate = get_rate(db, account.currency, user.base_currency, on_date)
    except ExchangeRateUnavailable as exc:
        raise _unprocessable(str(exc)) from exc

    label = description or f"Compensazione: {expense.description or 'credito'}"

    def _leg(signed: Decimal, **fields: Any) -> Transaction:
        return Transaction(
            account_id=account.id,
            amount=signed,
            currency=account.currency,
            amount_base_currency=signed * rate,
            exchange_rate=rate,
            date=on_date,
            description=label,
            source="manual",
            **fields,
        )

    spend = _leg(
        -amount,
        type="expense",
        category_id=spend_category_id,
        necessity_level_override=necessity_level_override,
    )
    repayment = _leg(
        amount,
        type="income",
        category_id=repayment_category_id,
        repays_transaction_id=expense.id,
    )
    db.add_all([spend, repayment])
    db.flush()  # assigns both ids so they can reference each other

    spend.offset_transaction_id = repayment.id
    repayment.offset_transaction_id = spend.id
    db.flush()
    return spend, repayment


def ensure_expense_keeps_covering_repayments(
    db: Session,
    expense: Transaction,
    *,
    new_amount: Decimal,
    new_lent_amount: Decimal | None,
) -> None:
    """
    An expense can't be edited into something its repayments contradict: a
    smaller fronted share than what already came back, or none at all, would
    leave repayments pointing at a credit that doesn't exist — 409.
    """
    repaid = repaid_by_expense(db, [expense.id]).get(expense.id, Decimal("0"))
    if new_lent_amount is None:
        if repaid > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This expense has repayments — delete them before removing "
                "the fronted amount",
            )
        return
    if new_lent_amount > abs(new_amount):
        raise _unprocessable("The amount fronted for others cannot exceed the expense")
    if new_lent_amount < repaid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{repaid} has already been paid back — the fronted amount cannot go below it",
        )


def ensure_date_precedes_repayments(db: Session, expense: Transaction, new_date: date_) -> None:
    """Moving an expense after a repayment would put the money back before it was spent — 409."""
    earliest = (
        db.query(func.min(Transaction.date))
        .filter(
            Transaction.repays_transaction_id == expense.id, Transaction.deleted_at.is_(None)
        )
        .scalar()
    )
    if earliest is not None and new_date > earliest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A repayment is dated {earliest.isoformat()} — "
            "the expense cannot be moved after it",
        )


def has_live_repayments(db: Session, expense_id: UUID) -> bool:
    return (
        db.query(Transaction.id)
        .filter(Transaction.repays_transaction_id == expense_id, Transaction.deleted_at.is_(None))
        .first()
        is not None
    )


# ---------------------------------------------------------------------------
# Net worth
# ---------------------------------------------------------------------------

@dataclass
class CreditLedger:
    """
    Every fronted amount and every repayment, in base currency at the
    expense's frozen rate, so the credit can be read as of any date without
    a query per date (the history chart samples dozens).
    """

    lent: list[tuple[date_, Decimal]] = field(default_factory=list)
    repaid: list[tuple[date_, Decimal]] = field(default_factory=list)

    def value_on(self, on_date: date_) -> Decimal:
        lent = sum((v for d, v in self.lent if d <= on_date), Decimal("0"))
        repaid = sum((v for d, v in self.repaid if d <= on_date), Decimal("0"))
        # Never negative: validate_repayment keeps repayments under the
        # fronted amount, so this only guards a hand-edited row.
        return max(Decimal("0"), lent - repaid)


def load_credit_ledger(db: Session, user: User) -> CreditLedger:
    expense = aliased(Transaction)
    lent_rows = (
        db.query(
            expense.date, expense.lent_amount * expense.exchange_rate
        )
        .join(Account, Account.id == expense.account_id)
        .filter(
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
            expense.deleted_at.is_(None),
            expense.type == "expense",
            expense.lent_amount.isnot(None),
        )
        .all()
    )
    repaid_rows = (
        db.query(Transaction.date, Transaction.amount * expense.exchange_rate)
        .join(expense, expense.id == Transaction.repays_transaction_id)
        .join(Account, Account.id == expense.account_id)
        .filter(
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
            Transaction.deleted_at.is_(None),
            expense.deleted_at.is_(None),
        )
        .all()
    )
    return CreditLedger(
        lent=[(row[0], Decimal(str(row[1]))) for row in lent_rows],
        repaid=[(row[0], Decimal(str(row[1]))) for row in repaid_rows],
    )
