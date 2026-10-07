"""
Transactions endpoints: CRUD, summary aggregation, and CSV import (preview
then confirm). The most involved router — it's the one that touches
currency conversion.
"""

import math
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.deps import get_current_user, get_db
from app.models import Account, AssetTransaction, Category, SavingsAllocation, Transaction, User
from app.schemas import (
    PaginationMeta,
    SummaryGroupBy,
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
    TransferCreate,
)
from app.schemas import (
    Transaction as TransactionSchema,
)
from app.services import csv_import as csv_import_service
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate
from app.services.ownership import get_owned_account, get_owned_leaf_category
from app.services.transfers import create_linked_transfer

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

    category = Category(
        user_id=user.id, name=MISC_CATEGORY_NAME, type=category_type, parent_id=None
    )
    db.add(category)
    # populates category.id without committing yet — the caller commits it
    # alongside the transaction that needed it
    db.flush()
    return category


def _validate_necessity_override(transaction_type: str, override: object) -> None:
    """
    A necessity level answers "how essential was this spend", so it only
    means anything on an expense. Income has no necessity, and a transfer
    isn't a spend at all — the planning engine's bucket queries filter
    `type = 'expense'` for exactly that reason, so an override stored on
    anything else would be silently ignored data. Reject it instead.
    """
    if override is not None and transaction_type != "expense":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="necessity_level_override can only be set on expense transactions",
        )


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


def _reject_amount_or_date_edit_on_a_linked_leg(
    transaction: Transaction, changed_fields: set[str]
) -> None:
    """
    The two legs of a giroconto must stay mirror images. Editing one side's
    amount or date would silently desynchronise them, so the answer is
    delete and recreate — unlike a portfolio cash leg, which has another
    screen that owns it, a plain giroconto has nowhere else to be edited.
    `category_id`/`description` stay free, as they do there.
    """
    if transaction.counterpart_transaction_id is None:
        return
    if not changed_fields & {"amount", "date"}:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "This transfer is one leg of a linked giroconto — "
            "delete it and create a new one instead of editing amount or date"
        ),
    )


def _soft_delete_with_counterpart(db: Session, transaction: Transaction) -> None:
    """
    Retire both legs together, plus any savings allocation the destination
    leg backed. Leaving the allocation behind would keep consuming the
    period's savings quota for money that was never actually moved.
    """
    now = datetime.now(UTC)
    legs = [transaction]

    if transaction.counterpart_transaction_id is not None:
        counterpart = db.get(Transaction, transaction.counterpart_transaction_id)
        if counterpart is not None and counterpart.deleted_at is None:
            legs.append(counterpart)

    for leg in legs:
        leg.deleted_at = now

    allocations = (
        db.query(SavingsAllocation)
        .filter(
            SavingsAllocation.transaction_id.in_([leg.id for leg in legs]),
            SavingsAllocation.deleted_at.is_(None),
        )
        .all()
    )
    for allocation in allocations:
        allocation.deleted_at = now


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
    if params.merge_transfer_legs and not params.account_id:
        # Drop the incoming leg (the positive one) of each linked pair. Done
        # in SQL rather than by the client so pagination counts stay right.
        query = query.filter(
            ~(Transaction.counterpart_transaction_id.isnot(None) & (Transaction.amount > 0))
        )

    total_items = query.count()
    rows = (
        query.options(selectinload(Transaction.counterpart))
        .order_by(Transaction.date.desc())
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
        .all()
    )

    return TransactionListResponse(
        # ORM rows; `Transaction` is a from_attributes model, so Pydantic
        # validates them on the way out.
        data=rows,  # type: ignore[arg-type]
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
    account = get_owned_account(db, payload.account_id, current_user)
    _validate_necessity_override(payload.type.value, payload.necessity_level_override)

    category_id = payload.category_id
    if category_id:
        category_id = get_owned_leaf_category(
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
        necessity_level_override=(
            payload.necessity_level_override.value
            if payload.necessity_level_override is not None
            else None
        ),
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@router.post(
    "/transfers", response_model=list[TransactionSchema], status_code=status.HTTP_201_CREATED
)
def create_transfer(
    payload: TransferCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Transaction]:
    """
    A manual giroconto: both legs, linked, in one commit. A plain
    `type: transfer` POST still exists for single-sided movements, but it
    only touches one account — moving money between two needs this.
    """
    from_account = get_owned_account(db, payload.from_account_id, current_user)
    to_account = get_owned_account(db, payload.to_account_id, current_user)
    category_id = (
        get_owned_leaf_category(db, payload.category_id, current_user, "transfer").id
        if payload.category_id
        else None
    )

    outgoing, incoming = create_linked_transfer(
        db,
        current_user,
        from_account=from_account,
        to_account=to_account,
        amount=payload.amount,
        on_date=payload.date,
        description=payload.description or "Giroconto",
        category_id=category_id,
    )
    db.commit()
    db.refresh(outgoing)
    db.refresh(incoming)
    return [outgoing, incoming]


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

    # Heterogeneous by construction: labels, plain columns and aggregates,
    # picked at runtime from `group_by`.
    month_col = func.to_char(Transaction.date, "YYYY-MM").label("month")
    columns: list[Any] = [
        func.sum(Transaction.amount_base_currency).label("total"),
        func.count(Transaction.id).label("count"),
    ]
    group_cols: list[Any] = []

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
    _reject_amount_or_date_edit_on_a_linked_leg(transaction, set(update_data))

    if "category_id" in update_data:
        if update_data["category_id"] is None:
            # Explicitly clearing the category on an expense/income transaction
            # falls back to "Varie", same rule as creation — never leave one
            # uncategorized.
            if transaction.type in ("expense", "income"):
                misc_category = _get_or_create_misc_category(db, current_user, transaction.type)
                update_data["category_id"] = misc_category.id
        else:
            update_data["category_id"] = get_owned_leaf_category(
                db, update_data["category_id"], current_user, transaction.type
            ).id

    if "necessity_level_override" in update_data:
        _validate_necessity_override(transaction.type, update_data["necessity_level_override"])

    # If amount or date changes, the frozen conversion must be recomputed —
    # otherwise amount_base_currency would silently drift out of sync.
    needs_recompute = "amount" in update_data or "date" in update_data
    for field, value in update_data.items():
        # Enum members (necessity_level_override) are stored as their string
        # value, like `type` on create.
        setattr(transaction, field, value.value if hasattr(value, "value") else value)

    # A giroconto is listed as one row, so its description and category are
    # edited once: keep the hidden leg in step, or it resurfaces stale under
    # the destination account's filter (and in a category filter).
    if transaction.counterpart is not None:
        if "description" in update_data:
            transaction.counterpart.description = transaction.description
        if "category_id" in update_data:
            transaction.counterpart.category_id = transaction.category_id

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
    _soft_delete_with_counterpart(db, transaction)
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
    get_owned_account(db, account_id, current_user)

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
    get_owned_account(db, preview.account_id, current_user)

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