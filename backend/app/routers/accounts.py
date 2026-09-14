"""
Accounts endpoints: CRUD with soft delete.

Mostly the template for `categories` and then the more involved
`transactions` router — the one exception is `create_account`'s optional
`starting_balance`, which needs the same currency-conversion path as a
transaction (see below).
"""

from datetime import date as date_
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Account, Currency, Transaction, User
from app.schemas import Account as AccountSchema, AccountCreate, AccountUpdate
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


def _get_owned_account(db: Session, account_id: UUID, user: User) -> Account:
    """
    Fetch an account by id, scoped to the current user and excluding
    soft-deleted rows. Used by every endpoint below so ownership and the
    soft-delete filter can't be forgotten in one of them.
    """
    account = (
        db.query(Account)
        .filter(
            Account.id == account_id,
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
        )
        .first()
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


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

    if payload.starting_balance:
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
    return _get_owned_account(db, account_id, current_user)


@router.patch("/{account_id}", response_model=AccountSchema)
def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Account:
    account = _get_owned_account(db, account_id, current_user)

    update_data = payload.model_dump(exclude_unset=True)
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
    from datetime import datetime, timezone

    account = _get_owned_account(db, account_id, current_user)
    account.deleted_at = datetime.now(timezone.utc)
    db.commit()
    # Note: transactions referencing this account are left untouched — the
    # frontend renders them with the account's last known name/currency by
    # keeping the FK intact rather than nulling it out.