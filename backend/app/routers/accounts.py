"""
Accounts endpoints: CRUD with soft delete.

Mostly the template for `categories` and then the more involved
`transactions` router — the one exception is `create_account`'s optional
`starting_balance`, which needs the same currency-conversion path as a
transaction (see below).

Closing is a PATCH of `closed_at` (null reopens). A closed account is not a
deleted one: it keeps its balance and history and stays in this list — it
only refuses movements dated after the close.
"""

from datetime import UTC
from datetime import date as date_
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import (
    Account,
    AssetTransaction,
    Currency,
    SavingsGoal,
    SavingsGoalSource,
    Transaction,
    User,
)
from app.schemas import Account as AccountSchema
from app.schemas import AccountCreate, AccountUpdate
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate
from app.services.flat_rate import source_account_ids
from app.services.ownership import get_owned_account

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


def _reject_if_holds_the_tax_provision(db: Session, account: Account, user: User) -> None:
    if account.id in source_account_ids(db, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account holds the tax provision — remove it from Fatture first",
        )


def _reject_if_funds_a_goal(db: Session, account: Account, user: User) -> None:
    funded_goal = (
        db.query(SavingsGoal)
        .join(SavingsGoalSource, SavingsGoalSource.goal_id == SavingsGoal.id)
        .filter(
            SavingsGoal.user_id == user.id,
            SavingsGoal.deleted_at.is_(None),
            SavingsGoalSource.account_id == account.id,
            SavingsGoalSource.deleted_at.is_(None),
        )
        .first()
    )
    if funded_goal is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This account funds the savings goal «{funded_goal.name}» — "
                "detach it from the goal first"
            ),
        )


def _check_can_close(db: Session, account: Account, closed_at: date_, user: User) -> None:
    """
    Closing is refused when the date would contradict the ledger: a movement
    after it would sit on an account that no longer existed, and every write
    path refuses those (`ensure_account_open_on`), so it couldn't even be
    re-dated afterwards. A goal is refused because the waterfall would keep
    suggesting transfers into an account that takes none.

    A non-zero balance is *not* refused: it stays in balances and net worth
    as it is — hiding it would misstate the total — and the UI warns.
    """
    if closed_at > date_.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The closing date can't be in the future",
        )

    last_movement = max(
        (
            d
            for d in (
                db.query(func.max(Transaction.date))
                .filter(Transaction.account_id == account.id, Transaction.deleted_at.is_(None))
                .scalar(),
                db.query(func.max(AssetTransaction.date))
                .filter(
                    AssetTransaction.account_id == account.id,
                    AssetTransaction.deleted_at.is_(None),
                )
                .scalar(),
            )
            if d is not None
        ),
        default=None,
    )
    if last_movement is not None and last_movement > closed_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The account has movements up to {last_movement.isoformat()} — "
                "close it on or after that date"
            ),
        )

    _reject_if_funds_a_goal(db, account, user)


@router.get("", response_model=list[AccountSchema])
def list_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Account]:
    return (
        db.query(Account)
        .filter(Account.user_id == current_user.id, Account.deleted_at.is_(None))
        .order_by(Account.name)
        .all()
    )


@router.post("", response_model=AccountSchema, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Account:
    currency_exists = db.get(Currency, payload.currency)
    if currency_exists is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown currency code: {payload.currency}",
        )

    # Resolve the rate BEFORE writing anything. `get_rate` can fail, and an
    # unresolvable rate must leave no trace of a half-created account —
    # which the previous ordering (add + flush, then get_rate) could not
    # guarantee back when the service committed the caller's session.
    rate = None
    if payload.starting_balance:
        try:
            rate = get_rate(db, payload.currency, current_user.base_currency, date_.today())
        except ExchangeRateUnavailable as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    account = Account(
        user_id=current_user.id,
        name=payload.name,
        type=payload.type.value,
        currency=payload.currency,
    )
    db.add(account)
    db.flush()  # populates account.id so the opening-balance transaction below can reference it

    if payload.starting_balance and rate is not None:
        # Modeled as a `transfer` transaction — like an inter-account
        # transfer, an opening balance isn't a categorizable spend/income,
        # so it's exempt from the "no category -> Varie" rule and never
        # counts toward a budget's spend.
        db.add(
            Transaction(
                account_id=account.id,
                category_id=None,
                amount=payload.starting_balance,
                currency=account.currency,
                amount_base_currency=payload.starting_balance * rate,
                exchange_rate=rate,
                date=date_.today(),
                description="Saldo iniziale",
                type="transfer",
                source="manual",
            )
        )

    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=AccountSchema)
def get_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Account:
    return get_owned_account(db, account_id, current_user)


@router.patch("/{account_id}", response_model=AccountSchema)
def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Account:
    account = get_owned_account(db, account_id, current_user)

    update_data = payload.model_dump(exclude_unset=True)
    if update_data.get("closed_at") is not None:
        _check_can_close(db, account, update_data["closed_at"], current_user)
    for field, value in update_data.items():
        # `type` arrives as an enum member; store its string value like on create.
        setattr(account, field, value.value if hasattr(value, "value") else value)

    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    from datetime import datetime

    account = get_owned_account(db, account_id, current_user)

    # A soft-deleted account vanishes from the balance map the waterfall
    # reads, so a savings goal funded by it would quietly report zero and
    # the cascade would suggest refilling it — into a deleted account.
    _reject_if_funds_a_goal(db, account, current_user)
    # Same for the P.IVA provision: its total would silently drop and the
    # gap would read as a shortfall.
    _reject_if_holds_the_tax_provision(db, account, current_user)

    account.deleted_at = datetime.now(UTC)
    db.commit()
    # Note: transactions referencing this account are left untouched — the
    # frontend renders them with the account's last known name/currency by
    # keeping the FK intact rather than nulling it out.