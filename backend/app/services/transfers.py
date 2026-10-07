"""
Two-sided giroconti.

A transfer between the user's own accounts is two rows: money out of one,
money into the other. Before this, nothing tied them together — deleting
one left the other orphaned and both balances wrong. `create_linked_transfer`
writes the pair and points each at the other.

Same-currency only for now, and the reason is worth stating: converting
would mean calling `get_rate` inside a loop that writes several rows, and
a cache miss there used to commit a half-finished state. That commit is
gone (services now flush), but the test suite still can't observe this
class of bug — conftest rolls back at the connection level, so an inner
commit is invisible — so the cheap, verifiable constraint wins until
there's a way to test the alternative.
"""

from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Account, Transaction, User
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate
from app.services.ownership import ensure_account_open_on


def create_linked_transfer(
    db: Session,
    user: User,
    *,
    from_account: Account,
    to_account: Account,
    amount: Decimal,
    on_date: date_,
    description: str,
    category_id: UUID | None = None,
) -> tuple[Transaction, Transaction]:
    """
    Write both legs of a giroconto and link them. Flushes but does not
    commit — the caller owns the transaction, so a batch of transfers
    either all lands or none does.

    `category_id` must already be validated as one of the user's transfer
    categories; both legs carry it, since the pair is listed as one row.
    """
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A transfer amount must be positive",
        )
    if from_account.id == to_account.id:
        # The legs would cancel out in the balance sum, leaving funding
        # unchanged while the allocation ledger still consumed the quota.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Source and destination accounts must differ",
        )
    if from_account.currency != to_account.currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cross-currency transfers are not supported yet "
                f"({from_account.currency} -> {to_account.currency})"
            ),
        )
    ensure_account_open_on(from_account, on_date)
    ensure_account_open_on(to_account, on_date)

    # Resolved before any write. With both legs in one currency this is the
    # short-circuit path when that currency is the base one, and a single
    # lookup otherwise — never a fetch in the middle of the pair.
    try:
        rate = get_rate(db, from_account.currency, user.base_currency, on_date)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    def _leg(account: Account, signed: Decimal) -> Transaction:
        return Transaction(
            account_id=account.id,
            # Optional, and never defaulted to "Varie": a transfer between
            # your own accounts isn't a spend, the category only organises it.
            category_id=category_id,
            amount=signed,
            currency=account.currency,
            amount_base_currency=signed * rate,
            exchange_rate=rate,
            date=on_date,
            description=description,
            type="transfer",
            source="manual",
        )

    outgoing = _leg(from_account, -amount)
    incoming = _leg(to_account, amount)
    db.add_all([outgoing, incoming])
    db.flush()  # assigns both ids so they can reference each other

    outgoing.counterpart_transaction_id = incoming.id
    incoming.counterpart_transaction_id = outgoing.id
    db.flush()

    return outgoing, incoming


def create_cash_leg(
    db: Session,
    *,
    account: Account,
    amount: Decimal,
    currency: str,
    rate: Decimal,
    on_date: date_,
    description: str,
    source: str = "manual",
    category_id: UUID | None = None,
) -> Transaction:
    """
    The one-sided cousin of a giroconto: money leaving an account to become
    something else the user owns (a holding, a car, a gold bar) or coming
    back from it. Recorded as a `transfer`, never expense/income — so it is
    exempt from the "Varie" fallback and stays out of spend reports — and
    without it the thing's value would be added to net worth on top of cash
    that still looks unspent.

    `amount` is already signed (negative = out of the account), `rate`
    already resolved by the caller, and `category_id` already validated as a
    transfer category. Flushes so the caller can store the id; never commits.
    """
    ensure_account_open_on(account, on_date)
    cash_transaction = Transaction(
        account_id=account.id,
        category_id=category_id,
        amount=amount,
        currency=currency,
        amount_base_currency=amount * rate,
        exchange_rate=rate,
        date=on_date,
        description=description,
        type="transfer",
        source=source,
    )
    db.add(cash_transaction)
    db.flush()
    return cash_transaction
