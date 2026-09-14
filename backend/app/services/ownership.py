"""
Ownership lookups shared by the routers.

Every router grew its own `_get_owned_account`, four identical copies by
the time the planning engine added one. The body is load-bearing — it is
what applies both the ownership filter and the soft-delete filter in one
place — so having four of it meant four places to forget one of the two.

Only `Account` is shared here. The other `_get_owned_*` helpers stay
private to their routers: each is used by a single router and several
carry rules specific to it (a category must be a leaf of a matching type,
a transaction is reached through its account), so hoisting them would
trade duplication for indirection without removing a real risk.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Account, User


def get_owned_account(db: Session, account_id: UUID, user: User) -> Account:
    """
    Fetch an account by id, scoped to the user and excluding soft-deleted
    rows. 404 otherwise — never 403, so the response can't be used to probe
    which account ids exist.
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
