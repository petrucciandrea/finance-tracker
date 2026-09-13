"""
Transactions endpoints: CRUD, summary aggregation, and CSV import (preview
then confirm). The most involved router — it's the one that touches
currency conversion.
"""

import math
from datetime import datetime, timezone
from uuid import UUID

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Account, AssetTransaction, Category, Transaction, User
from app.schemas import (
    PaginationMeta,
    SummaryGroupBy,
    Transaction as TransactionSchema,
    TransactionCreate,
    TransactionImportConfirm,
    TransactionImportPreview,
    TransactionImportRow,
    TransactionListParams,
    TransactionListResponse,
    TransactionSummaryItem,
    TransactionSummaryParams,
    TransactionSummaryResponse,
    TransactionUpdate,
)
from app.services import csv_import as csv_import_service
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


MISC_CATEGORY_NAME = "Varie"


def _get_or_create_misc_category(db: Session, user: User, category_type: str) -> Category:
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

    category = Category(user_id=user.id, name=MISC_CATEGORY_NAME, type=category_type, parent_id=None)
    db.add(category)
    db.flush()  # populates category.id without committing yet — caller commits alongside the transaction
    return category


def _get_owned_leaf_category(
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


def _get_owned_account_or_404(db: Session, account_id: UUID, user: User) -> Account:
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == user.id, Account.deleted_at.is_(None))
        .first()
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


def _get_owned_transaction(db: Session, transaction_id: UUID, user: User) -> Transaction:
    transaction = (
        db.query(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Transaction.id == transaction_id,
            Account.user_id == user.id,
            Transaction.deleted_at.is_(None),
        )
        .first()
    )
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return transaction


def _reject_if_linked_to_asset_transaction(
    db: Session, transaction_id: UUID, changed_fields: set[str] | None = None
) -> None:
    """
    A portfolio buy/sell owns its cash-side `transfer` Transaction's
    `amount`/`date` (see routers/portfolio.py) — editing those here directly
    would let the cash movement drift out of sync with the asset transaction
    that caused it, silently corrupting net worth. `category_id`/
    `description` are free to edit here (e.g. tagging every buy/sell with an
    "Investimenti" category), since they don't feed into that math.
    `changed_fields=None` means "deleting" — always rejected, since only
    deleting the asset transaction can retire its cash movement correctly.
    """
    if changed_fields is not None and not changed_fields & {"amount", "date"}:
        return

    linked = (
        db.query(AssetTransaction)
        .filter(
            AssetTransaction.transaction_id == transaction_id,
            AssetTransaction.deleted_at.is_(None),
        )
        .first()
    )
    if linked is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This transaction's amount/date are managed by a portfolio "
            "operation — edit or delete it from Portfolio instead",
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=TransactionListResponse)
def list_transactions(
    params: Annotated[TransactionListParams, Query()],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TransactionListResponse:
    query = (
        db.query(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .filter(Account.user_id == current_user.id, Transaction.deleted_at.is_(None))
    )

    if params.date_from:
        query = query.filter(Transaction.date >= params.date_from)
    if params.date_to:
        query = query.filter(Transaction.date <= params.date_to)
    if params.category_id:
        query = query.filter(Transaction.category_id == params.category_id)
    if params.account_id:
        query = query.filter(Transaction.account_id == params.account_id)
    if params.currency:
        query = query.filter(Transaction.currency == params.currency)
    if params.type:
        query = query.filter(Transaction.type == params.type.value)

    total_items = query.count()
    rows = (
        query.order_by(Transaction.date.desc())
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
        .all()
    )

    return TransactionListResponse(
        data=rows,
        meta=PaginationMeta(
            page=params.page,
            page_size=params.page_size,
            total_items=total_items,
            total_pages=math.ceil(total_items / params.page_size) if total_items else 0,
        ),
    )


@router.post("", response_model=TransactionSchema, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Transaction:
    account = _get_owned_account_or_404(db, payload.account_id, current_user)

    category_id = payload.category_id
    if category_id:
        category_id = _get_owned_leaf_category(
            db, category_id, current_user, payload.type.value
        ).id
    elif payload.type in ("expense", "income"):
        # No category given for a spend/income transaction — fall back to
        # "Varie" instead of allowing an uncategorized expense/income to
        # silently exist (transfers are exempt, see _get_or_create_misc_category).
        category_id = _get_or_create_misc_category(db, current_user, payload.type).id

    try:
        rate = get_rate(db, payload.currency, current_user.base_currency, payload.date)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    transaction = Transaction(
        account_id=account.id,
        category_id=category_id,
        amount=payload.amount,
        currency=payload.currency,
        amount_base_currency=payload.amount * rate,
        exchange_rate=rate,
        date=payload.date,
        description=payload.description,
        type=payload.type.value,
        source="manual",
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@router.get("/summary", response_model=TransactionSummaryResponse)
def summary(
    params: Annotated[TransactionSummaryParams, Query()],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TransactionSummaryResponse:
    """
    Aggregation done in SQL (GROUP BY), not in Python, so it stays fast as
    transaction volume grows. `group_by` controls which columns are selected
    and grouped on — month, category, or both (cross-tab).
    """
    # Default here, not on the schema field — the schema's own
    # default_factory conflicts with how FastAPI resolves query-parameter
    # models for list fields (raises a validation error instead of using
    # the factory), so None-as-default plus a fallback here is the workaround.
    group_by = params.group_by or [SummaryGroupBy.month]
    group_by_month = SummaryGroupBy.month in group_by
    group_by_category = SummaryGroupBy.category in group_by

    month_col = func.to_char(Transaction.date, "YYYY-MM").label("month")
    columns = [
        func.sum(Transaction.amount_base_currency).label("total"),
        func.count(Transaction.id).label("count"),
    ]
    group_cols = []

    if group_by_month:
        columns.append(month_col)
        group_cols.append(month_col)
    if group_by_category:
        columns.extend([Category.id.label("category_id"), Category.name.label("category_name")])
        group_cols.extend([Category.id, Category.name])

    query = (
        db.query(*columns)
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .filter(
            Account.user_id == current_user.id,
            Transaction.deleted_at.is_(None),
            # A transfer (opening balance, portfolio buy/sell cash movement,
            # ...) isn't income or spend — it's money moving between the
            # user's own buckets, so it must never inflate/deflate this
            # income/expense summary. Same rule budgets.py's status query
            # already applies with its own `type == "expense"` filter.
            Transaction.type != "transfer",
        )
    )

    if params.date_from:
        query = query.filter(Transaction.date >= params.date_from)
    if params.date_to:
        query = query.filter(Transaction.date <= params.date_to)
    if params.currency:
        query = query.filter(Transaction.currency == params.currency)

    if group_cols:
        query = query.group_by(*group_cols)

    results = query.all()

    items = [
        TransactionSummaryItem(
            month=row._mapping.get("month"),
            category_id=row._mapping.get("category_id"),
            category_name=row._mapping.get("category_name"),
            total_amount_base_currency=row._mapping["total"],
            transaction_count=row._mapping["count"],
        )
        for row in results
    ]
    return TransactionSummaryResponse(data=items)


@router.get("/{transaction_id}", response_model=TransactionSchema)
def get_transaction(
    transaction_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Transaction:
    return _get_owned_transaction(db, transaction_id, current_user)


@router.patch("/{transaction_id}", response_model=TransactionSchema)
def update_transaction(
    transaction_id: UUID,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Transaction:
    transaction = _get_owned_transaction(db, transaction_id, current_user)
    update_data = payload.model_dump(exclude_unset=True)
    _reject_if_linked_to_asset_transaction(db, transaction.id, changed_fields=set(update_data))

    if "category_id" in update_data:
        if update_data["category_id"] is None:
            # Explicitly clearing the category on an expense/income transaction
            # falls back to "Varie", same rule as creation — never leave one
            # uncategorized.
            if transaction.type in ("expense", "income"):
                misc_category = _get_or_create_misc_category(db, current_user, transaction.type)
                update_data["category_id"] = misc_category.id
        else:
            update_data["category_id"] = _get_owned_leaf_category(
                db, update_data["category_id"], current_user, transaction.type
            ).id

    # If amount or date changes, the frozen conversion must be recomputed —
    # otherwise amount_base_currency would silently drift out of sync.
    needs_recompute = "amount" in update_data or "date" in update_data
    for field, value in update_data.items():
        setattr(transaction, field, value)

    if needs_recompute:
        try:
            rate = get_rate(db, transaction.currency, current_user.base_currency, transaction.date)
        except ExchangeRateUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        transaction.exchange_rate = rate
        transaction.amount_base_currency = transaction.amount * rate

    db.commit()
    db.refresh(transaction)
    return transaction


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    transaction = _get_owned_transaction(db, transaction_id, current_user)
    _reject_if_linked_to_asset_transaction(db, transaction.id)
    transaction.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------------------
# CSV import — two-step: upload/preview, then confirm
# ---------------------------------------------------------------------------

@router.post("/import", response_model=TransactionImportPreview)
async def import_preview(
    account_id: UUID,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TransactionImportPreview:
    _get_owned_account_or_404(db, account_id, current_user)

    content = await file.read()
    preview = csv_import_service.parse_csv(db, account_id, content)

    rows = [
        TransactionImportRow(
            row_number=r.row_number,
            account_id=r.account_id,
            date=r.date,
            amount=r.amount,
            currency=r.currency,
            description=r.description,
            suggested_category_id=r.suggested_category_id,
            is_duplicate=r.is_duplicate,
            is_parsable=r.is_parsable,
            error=r.error,
        )
        for r in preview.rows
    ]
    return TransactionImportPreview(
        import_id=preview.import_id,
        rows=rows,
        total_rows=len(rows),
        parsable_rows=sum(1 for r in rows if r.is_parsable),
        duplicate_rows=sum(1 for r in rows if r.is_duplicate),
    )


@router.post("/import/confirm", response_model=list[TransactionSchema])
def import_confirm(
    payload: TransactionImportConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Transaction]:
    preview = csv_import_service.get_preview(payload.import_id)
    if preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import preview not found or expired — please re-upload the file",
        )
    _get_owned_account_or_404(db, preview.account_id, current_user)

    selected = {r.row_number: r for r in preview.rows if r.row_number in payload.row_numbers}
    created: list[Transaction] = []

    for row in selected.values():
        if not row.is_parsable:
            continue  # silently skip — the frontend shouldn't have sent these anyway
        try:
            rate = get_rate(db, row.currency, current_user.base_currency, row.date)
        except ExchangeRateUnavailable:
            continue  # a partial import beats failing the whole batch on one bad row

        transaction_type = "expense" if row.amount < 0 else "income"
        # Imported rows are always expense/income (never transfer), so the
        # same "no category -> Varie" rule as manual creation applies here.
        category_id = row.suggested_category_id or _get_or_create_misc_category(
            db, current_user, transaction_type
        ).id

        created.append(
            Transaction(
                account_id=row.account_id,
                category_id=category_id,
                amount=row.amount,
                currency=row.currency,
                amount_base_currency=row.amount * rate,
                exchange_rate=rate,
                date=row.date,
                description=row.description,
                type=transaction_type,
                source="import",
            )
        )

    db.add_all(created)
    db.commit()
    for t in created:
        db.refresh(t)

    csv_import_service.discard_preview(payload.import_id)
    return created