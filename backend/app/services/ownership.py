"""
Ownership lookups shared by the routers.

Every router grew its own `_get_owned_account`, four identical copies by
the time the planning engine added one. The body is load-bearing — it is
what applies both the ownership filter and the soft-delete filter in one
place — so having four of it meant four places to forget one of the two.

`Account` is shared here, and so is the leaf-category lookup now that a
portfolio buy/sell can file its cash leg under a transfer category too.
The "Varie" fallback moved here once collecting an invoice started writing
income transactions outside the transactions router.
The other `_get_owned_*` helpers stay private to their routers: each is
used by a single router, so hoisting them would trade duplication for
indirection without removing a real risk.
"""

from datetime import date as date_
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Account, Category, User


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


def ensure_account_open_on(account: Account, on_date: date_) -> None:
    """
    A closed account takes no movement dated after its closing day — 409.

    Back-dated ones still go through: fixing history before the close is
    legitimate, and refusing it would force a reopen-edit-reclose round trip
    for a typo. Called by every path that writes or re-dates a movement,
    including the shared transfer and cash-leg helpers.
    """
    if account.closed_at is not None and on_date > account.closed_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The account «{account.name}» was closed on "
                f"{account.closed_at.isoformat()} — reopen it first"
            ),
        )


def get_owned_leaf_category(
    db: Session, category_id: UUID, user: User, expected_type: str
) -> Category:
    """
    A transaction can only be filed under a category that: belongs to the
    user, has no active subcategories of its own (pick one of them instead,
    so spend doesn't land on an ambiguous parent bucket), and shares the
    transaction's own type — an expense category on a transfer (or vice
    versa) would be meaningless, now that categories exist for all three
    transaction types (expense/income/transfer).
    """
    category = (
        db.query(Category)
        .filter(
            Category.id == category_id,
            Category.user_id == user.id,
            Category.deleted_at.is_(None),
        )
        .first()
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    if category.type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Category type '{category.type}' does not match "
                f"transaction type '{expected_type}'"
            ),
        )

    has_active_children = (
        db.query(Category)
        .filter(Category.parent_id == category.id, Category.deleted_at.is_(None))
        .first()
        is not None
    )
    if has_active_children:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This category has subcategories — "
                "assign the transaction to a subcategory instead"
            ),
        )
    return category


MISC_CATEGORY_NAME = "Varie"


def get_or_create_misc_category(db: Session, user: User, category_type: str) -> Category:
    """
    Transactions of type expense/income must always have a category — if the
    client sends none, fall back to a "Varie" category of the matching type,
    creating it on first use. `type: transfer` is exempt: a transfer between
    the user's own accounts isn't a spend/income event, so it isn't forced
    into "Varie" here.
    """
    existing = (
        db.query(Category)
        .filter(
            Category.user_id == user.id,
            Category.name == MISC_CATEGORY_NAME,
            Category.type == category_type,
            Category.deleted_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        return existing

    category = Category(
        user_id=user.id, name=MISC_CATEGORY_NAME, type=category_type, parent_id=None
    )
    db.add(category)
    # populates category.id without committing yet — the caller commits it
    # alongside the transaction that needed it
    db.flush()
    return category
