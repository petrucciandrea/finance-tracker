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
from app.models import Account, Category, Transaction, User
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

    if payload.category_id:
        category_ok = (
            db.query(Category)
            .filter(
                Category.id == payload.category_id,
                Category.user_id == current_user.id,
                Category.deleted_at.is_(None),
            )
            .first()
        )
        if category_ok is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    try:
        rate = get_rate(db, payload.currency, current_user.base_currency, payload.date)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    transaction = Transaction(
        account_id=account.id,
        category_id=payload.category_id,
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
    group_by_month = SummaryGroupBy.month in params.group_by
    group_by_category = SummaryGroupBy.category in params.group_by

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
        .filter(Account.user_id == current_user.id, Transaction.deleted_at.is_(None))
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
            month=getattr(row, "month", None),
            category_id=getattr(row, "category_id", None),
            category_name=getattr(row, "category_name", None),
            total_amount_base_currency=row.total,
            transaction_count=row.count,
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

        created.append(
            Transaction(
                account_id=row.account_id,
                category_id=row.suggested_category_id,
                amount=row.amount,
                currency=row.currency,
                amount_base_currency=row.amount * rate,
                exchange_rate=rate,
                date=row.date,
                description=row.description,
                type="expense" if row.amount < 0 else "income",
                source="import",
            )
        )

    db.add_all(created)
    db.commit()
    for t in created:
        db.refresh(t)

    csv_import_service.discard_preview(payload.import_id)
    return created