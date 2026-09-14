"""
Necessity taxonomy aggregations — the shared foundation of the planning
engine. Every bucket figure in the allocation status, the survival budget
and the scenario simulator comes from here, so the awkward parts live in
one place instead of being re-derived (and re-broken) per endpoint.

Three rules this module exists to enforce:

1. **Inheritance.** A transaction's effective necessity is
   `COALESCE(override, category.necessity_level, parent.necessity_level)`.
   Both joins must be LEFT: `category_id` is nullable, and an INNER JOIN
   would silently drop rows rather than reporting them as unclassified.

2. **Transfers are not spend.** `type = 'transfer'` rows carry
   `category_id = NULL` (opening balances, portfolio cash legs) and a
   negative amount, so without an explicit `type = 'expense'` filter they
   would read as a large unclassified expense. Same rule budgets.py and
   the transactions summary already apply.

3. **Signs are flipped at the boundary.** Expenses are stored negative;
   every function here returns positive magnitudes, so callers never have
   to remember which way round a "spend" is.
"""

from datetime import date as date_
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.models import Account, Category, Transaction, User

# The bucket key used for spend whose category carries no necessity level
# (and whose parent carries none either). Kept as an explicit constant
# rather than a bare None literal scattered across call sites, because the
# whole point is that unclassified spend stays visible instead of being
# folded into 'primary'.
UNCLASSIFIED = None


def _effective_necessity_expression(category: Any, parent: Any) -> Any:
    """The COALESCE chain of rule 1, as a SQL expression."""
    return func.coalesce(
        Transaction.necessity_level_override,
        category.necessity_level,
        parent.necessity_level,
    )


def spend_by_necessity(
    db: Session, user: User, *, date_from: date_, date_to: date_
) -> dict[str | None, Decimal]:
    """
    Total expense per necessity bucket over an inclusive date range, in the
    user's base currency, as positive amounts. Buckets with no spend are
    absent; unclassified spend is keyed by `UNCLASSIFIED`.
    """
    category = aliased(Category)
    parent = aliased(Category)
    bucket = _effective_necessity_expression(category, parent).label("bucket")

    rows = (
        db.query(
            bucket,
            func.coalesce(func.sum(Transaction.amount_base_currency), 0).label("total"),
        )
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(category, category.id == Transaction.category_id)
        .outerjoin(parent, parent.id == category.parent_id)
        .filter(
            Account.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.type == "expense",
            Transaction.date >= date_from,
            Transaction.date <= date_to,
        )
        .group_by(bucket)
        .all()
    )

    # Expenses are stored negative; callers want a positive "amount spent",
    # same convention as budgets.py's status.
    return {
        row._mapping["bucket"]: -Decimal(str(row._mapping["total"])) for row in rows
    }


def spend_by_necessity_and_category(
    db: Session, user: User, *, date_from: date_, date_to: date_
) -> list[tuple[str | None, UUID | None, Decimal]]:
    """
    The same expense total as `spend_by_necessity`, but broken down one
    level finer, as `(bucket, category_id, positive_amount)` rows.

    The simulator needs this grain to honour its precedence rule: a cut
    aimed at one category must win over a cut aimed at the bucket that
    contains it, and the category must then be excluded from the bucket
    cut's base. Applying both to a single per-bucket total would count that
    category's spend twice.
    """
    category = aliased(Category)
    parent = aliased(Category)
    bucket = _effective_necessity_expression(category, parent).label("bucket")

    rows = (
        db.query(
            bucket,
            Transaction.category_id.label("category_id"),
            func.coalesce(func.sum(Transaction.amount_base_currency), 0).label("total"),
        )
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(category, category.id == Transaction.category_id)
        .outerjoin(parent, parent.id == category.parent_id)
        .filter(
            Account.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.type == "expense",
            Transaction.date >= date_from,
            Transaction.date <= date_to,
        )
        .group_by(bucket, Transaction.category_id)
        .all()
    )

    return [
        (
            row._mapping["bucket"],
            row._mapping["category_id"],
            -Decimal(str(row._mapping["total"])),
        )
        for row in rows
    ]


def income_total(db: Session, user: User, *, date_from: date_, date_to: date_) -> Decimal:
    """
    Income over an inclusive range, in base currency — the denominator of
    the whole allocation model.

    Two corrections that are easy to miss:

    - Categories flagged `excluded_from_income_base` are left out. CSV
      import types rows by sign alone, so refunds, reversals and cashback
      all arrive as `income`; counting them would inflate both the
      50/25/15/10 split and the savings quota derived from it.
    - The result is clamped at zero. Nothing validates sign against type
      (there isn't a single validator on TransactionCreate), so a salary
      reversal booked as negative income is one POST away — and a negative
      quota would make the waterfall propose transfers in reverse.
    """
    category = aliased(Category)

    total = (
        db.query(func.coalesce(func.sum(Transaction.amount_base_currency), 0))
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(category, category.id == Transaction.category_id)
        .filter(
            Account.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.type == "income",
            Transaction.date >= date_from,
            Transaction.date <= date_to,
            # A transaction with no category can't be opted out, so NULL
            # must pass rather than being swallowed by the comparison.
            func.coalesce(category.excluded_from_income_base, False).is_(False),
        )
        .scalar()
    )

    return max(Decimal("0"), Decimal(str(total)))


def income_by_category(
    db: Session, user: User, *, date_from: date_, date_to: date_
) -> list[dict]:
    """
    Income broken down by category, including the categories excluded from
    the base. The allocation status surfaces this so the user can see what
    is being counted as income and opt the wrong things out — without it,
    an inflated denominator is invisible.
    """
    category = aliased(Category)

    rows = (
        db.query(
            category.id.label("category_id"),
            category.name.label("category_name"),
            func.coalesce(category.excluded_from_income_base, False).label("excluded"),
            func.coalesce(func.sum(Transaction.amount_base_currency), 0).label("total"),
        )
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(category, category.id == Transaction.category_id)
        .filter(
            Account.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.type == "income",
            Transaction.date >= date_from,
            Transaction.date <= date_to,
        )
        .group_by(category.id, category.name, category.excluded_from_income_base)
        .all()
    )

    return [
        {
            "category_id": row._mapping["category_id"],
            "category_name": row._mapping["category_name"],
            "excluded_from_income_base": bool(row._mapping["excluded"]),
            "total_amount_base_currency": Decimal(str(row._mapping["total"])),
        }
        for row in rows
    ]


def classification_coverage(buckets: dict[str | None, Decimal]) -> float:
    """
    Share of spend that resolved to a necessity level, as a percentage.

    The planning numbers are only as trustworthy as this figure: a user who
    has classified nothing gets a survival budget of zero, which is not the
    same statement as "you need nothing to survive". Surfacing coverage is
    what keeps that distinction visible in the UI.
    """
    total = sum(buckets.values(), Decimal("0"))
    if total == 0:
        return 0.0
    classified = sum(
        (amount for level, amount in buckets.items() if level is not UNCLASSIFIED),
        Decimal("0"),
    )
    return round(float(classified / total * 100), 1)
