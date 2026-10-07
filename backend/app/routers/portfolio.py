"""
Portfolio endpoints: holdings CRUD, asset search, net worth, and CSV import
(preview then confirm — same two-step shape as `transactions.py`'s, just
against `AssetTransaction` instead of `Transaction`).

One combined router rather than separate `assets.py` / `holdings.py` files:
`Asset` has no standalone CRUD from a user's perspective — it's resolved
implicitly the same way `Currency` is, never independently created/edited by
a user — and prices/holdings/net-worth/import are all inseparable from each
other for the same reason CSV import lives inside `transactions.py` instead
of its own file.
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from app.deps import get_current_user, get_db
from app.models import Account, Asset, AssetTransaction, PhysicalAsset, Transaction, User
from app.schemas import (
    AssetSearchResult,
    AssetTransactionCreate,
    AssetTransactionImportConfirm,
    AssetTransactionImportPreview,
    AssetTransactionImportRow,
    AssetTransactionType,
    AssetTransactionUpdate,
    AssetType,
    HoldingWithValue,
    NetWorthSummary,
    PortfolioHistoryPeriod,
    PortfolioHistoryPoint,
    PortfolioHistoryResponse,
)
from app.schemas import (
    AssetTransaction as AssetTransactionSchema,
)
from app.services import asset_prices as asset_prices_service
from app.services import csv_import as csv_import_service
from app.services import physical_assets as physical_assets_service
from app.services.asset_prices import AssetPriceUnavailable
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate, get_rate_history
from app.services.net_worth import (
    account_balances,
    holdings_with_value,
    user_asset_transactions_query,
)
from app.services.ownership import get_owned_account, get_owned_leaf_category
from app.services.physical_assets import physical_assets_with_value
from app.services.transfers import create_cash_leg

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


def _cash_movement_description(asset_symbol: str, asset_transaction_type: str) -> str:
    verb = "Acquisto" if asset_transaction_type == "buy" else "Vendita"
    return f"{verb} {asset_symbol}"


def _signed_cash_amount(asset_transaction_type: str, total: Decimal) -> Decimal:
    # A buy pulls cash out of the account (negative); a sell returns cash to
    # it (positive) — mirrors the sign convention transactions.py already
    # uses for expense (negative) vs income (positive).
    return -total if asset_transaction_type == "buy" else total


def _create_linked_cash_transaction(
    db: Session,
    *,
    account: Account,
    asset: Asset,
    asset_transaction_type: str,
    total: Decimal,
    rate: Decimal,
    on_date: date_,
    source: str,
    category_id: UUID | None = None,
) -> Transaction:
    """
    Every buy/sell moves cash in or out of the account it's logged on — see
    `services/transfers.py:create_cash_leg` for why that is a `transfer`.
    """
    return create_cash_leg(
        db,
        account=account,
        amount=_signed_cash_amount(asset_transaction_type, total),
        currency=asset.currency,
        rate=rate,
        on_date=on_date,
        description=_cash_movement_description(asset.symbol, asset_transaction_type),
        source=source,
        category_id=category_id,
    )


def _get_owned_asset_transaction(db: Session, transaction_id: UUID, user: User) -> AssetTransaction:
    transaction = (
        db.query(AssetTransaction)
        .join(Account, Account.id == AssetTransaction.account_id)
        .options(joinedload(AssetTransaction.asset))
        .filter(
            AssetTransaction.id == transaction_id,
            AssetTransaction.deleted_at.is_(None),
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
        )
        .first()
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Asset transaction not found"
        )
    return transaction


def _current_quantity(
    db: Session, account_id: UUID, asset_id: UUID, exclude_transaction_id: UUID | None = None
) -> Decimal:
    """
    Total held quantity for (account, asset) is just sum(buys) - sum(sells) —
    unlike average cost, it doesn't depend on transaction order, so this
    doesn't need the full weighted-average walk below just to validate a
    sell isn't overdrawing the position.
    """
    query = db.query(AssetTransaction).filter(
        AssetTransaction.account_id == account_id,
        AssetTransaction.asset_id == asset_id,
        AssetTransaction.deleted_at.is_(None),
    )
    if exclude_transaction_id is not None:
        query = query.filter(AssetTransaction.id != exclude_transaction_id)

    total = Decimal("0")
    for tx in query.all():
        quantity = Decimal(str(tx.quantity))
        total += quantity if tx.type == "buy" else -quantity
    return total


def _sample_dates(start_date: date_, end_date: date_) -> list[date_]:
    """Daily points for a range up to ~3 months, weekly beyond that, always ending today."""
    span_days = (end_date - start_date).days
    if span_days <= 0:
        return [end_date]

    step = 1 if span_days <= 90 else 7
    dates = [start_date + timedelta(days=offset) for offset in range(0, span_days, step)]
    if dates[-1] != end_date:
        dates.append(end_date)
    return dates


@router.get("/assets/search", response_model=list[AssetSearchResult])
def search_assets(
    q: str,
    asset_type: AssetType,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return asset_prices_service.search_assets(q, asset_type.value)


@router.get("/holdings", response_model=list[HoldingWithValue])
def list_holdings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[HoldingWithValue]:
    holdings = holdings_with_value(db, current_user)
    # A read that writes: price and rate lookups populate their caches but
    # no longer commit the session themselves, so persist them here. Without
    # this the provider would be hit again on every single request.
    db.commit()
    return holdings


@router.get("/transactions", response_model=list[AssetTransactionSchema])
def list_asset_transactions(
    account_id: UUID | None = None,
    asset_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AssetTransaction]:
    query = user_asset_transactions_query(db, current_user)
    if account_id is not None:
        query = query.filter(AssetTransaction.account_id == account_id)
    if asset_id is not None:
        query = query.filter(AssetTransaction.asset_id == asset_id)
    return query.order_by(AssetTransaction.date.desc(), AssetTransaction.created_at.desc()).all()


@router.post(
    "/transactions", response_model=AssetTransactionSchema, status_code=status.HTTP_201_CREATED
)
def create_asset_transaction(
    payload: AssetTransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetTransaction:
    account = get_owned_account(db, payload.account_id, current_user)
    if account.type not in ("investment", "crypto_wallet"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Asset transactions can only be logged on investment or crypto wallet accounts",
        )
    # Checked before the asset lookup, which may already write a row.
    category_id = (
        get_owned_leaf_category(db, payload.category_id, current_user, "transfer").id
        if payload.category_id
        else None
    )

    try:
        asset = asset_prices_service.find_or_create_asset(
            db, payload.symbol, payload.asset_type.value
        )
        asset_prices_service.get_price(db, asset, date_.today())
    except AssetPriceUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if payload.type == AssetTransactionType.sell:
        held = _current_quantity(db, account.id, asset.id)
        if payload.quantity > held:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot sell {payload.quantity} — only {held} currently held",
            )

    try:
        rate = get_rate(db, asset.currency, current_user.base_currency, payload.date)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    gross = payload.quantity * payload.price
    total = gross + payload.fee if payload.type == AssetTransactionType.buy else gross - payload.fee

    cash_transaction = _create_linked_cash_transaction(
        db,
        account=account,
        asset=asset,
        asset_transaction_type=payload.type.value,
        total=total,
        rate=rate,
        on_date=payload.date,
        source="manual",
        category_id=category_id,
    )

    transaction = AssetTransaction(
        account_id=account.id,
        asset_id=asset.id,
        transaction_id=cash_transaction.id,
        type=payload.type.value,
        quantity=payload.quantity,
        price=payload.price,
        fee=payload.fee,
        amount_base_currency=total * rate,
        exchange_rate=rate,
        date=payload.date,
        notes=payload.notes,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@router.patch("/transactions/{transaction_id}", response_model=AssetTransactionSchema)
def update_asset_transaction(
    transaction_id: UUID,
    payload: AssetTransactionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetTransaction:
    transaction = _get_owned_asset_transaction(db, transaction_id, current_user)
    update_data = payload.model_dump(exclude_unset=True)

    if transaction.type == "sell":
        new_quantity = Decimal(str(update_data.get("quantity", transaction.quantity)))
        held = _current_quantity(
            db, transaction.account_id, transaction.asset_id, exclude_transaction_id=transaction.id
        )
        if new_quantity > held:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot sell {new_quantity} — only {held} currently held",
            )

    # Sign convention frozen at write time, same rule as Transaction: editing
    # a note must not touch it, but quantity/price/fee/date all feed into it.
    needs_recompute = any(field in update_data for field in ("quantity", "price", "fee", "date"))
    for field, value in update_data.items():
        setattr(transaction, field, value)

    if needs_recompute:
        try:
            rate = get_rate(
                db, transaction.asset.currency, current_user.base_currency, transaction.date
            )
        except ExchangeRateUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        gross = transaction.quantity * transaction.price
        total = gross + transaction.fee if transaction.type == "buy" else gross - transaction.fee
        transaction.exchange_rate = rate
        transaction.amount_base_currency = total * rate

        if transaction.transaction_id is not None:
            cash_transaction = db.get(Transaction, transaction.transaction_id)
            if cash_transaction is not None:
                signed_amount = _signed_cash_amount(transaction.type, total)
                cash_transaction.amount = signed_amount
                cash_transaction.amount_base_currency = signed_amount * rate
                cash_transaction.exchange_rate = rate
                cash_transaction.date = transaction.date

    db.commit()
    db.refresh(transaction)
    return transaction


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset_transaction(
    transaction_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    transaction = _get_owned_asset_transaction(db, transaction_id, current_user)
    transaction.deleted_at = datetime.now(UTC)
    if transaction.transaction_id is not None:
        cash_transaction = db.get(Transaction, transaction.transaction_id)
        if cash_transaction is not None:
            cash_transaction.deleted_at = datetime.now(UTC)
    db.commit()


# ---------------------------------------------------------------------------
# CSV import — two-step: upload/preview, then confirm (mirrors
# transactions.py's import flow, against AssetTransaction instead)
# ---------------------------------------------------------------------------

@router.post("/transactions/import", response_model=AssetTransactionImportPreview)
async def asset_transaction_import_preview(
    account_id: UUID,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssetTransactionImportPreview:
    account = get_owned_account(db, account_id, current_user)
    if account.type not in ("investment", "crypto_wallet"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Asset transactions can only be imported into investment or crypto "
            "wallet accounts",
        )

    content = await file.read()
    preview = csv_import_service.parse_asset_csv(db, account_id, content)

    rows = [
        AssetTransactionImportRow(
            row_number=r.row_number,
            account_id=r.account_id,
            symbol=r.symbol,
            asset_type=AssetType(r.asset_type),
            type=AssetTransactionType(r.type),
            quantity=r.quantity,
            price=r.price,
            fee=r.fee,
            date=r.date,
            notes=r.notes,
            is_duplicate=r.is_duplicate,
            is_parsable=r.is_parsable,
            error=r.error,
        )
        for r in preview.rows
    ]
    return AssetTransactionImportPreview(
        import_id=preview.import_id,
        rows=rows,
        total_rows=len(rows),
        parsable_rows=sum(1 for r in rows if r.is_parsable),
        duplicate_rows=sum(1 for r in rows if r.is_duplicate),
    )


@router.post("/transactions/import/confirm", response_model=list[AssetTransactionSchema])
def asset_transaction_import_confirm(
    payload: AssetTransactionImportConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AssetTransaction]:
    preview = csv_import_service.get_asset_preview(payload.import_id)
    if preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import preview not found or expired — please re-upload the file",
        )
    account = get_owned_account(db, preview.account_id, current_user)
    if account.type not in ("investment", "crypto_wallet"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Asset transactions can only be imported into investment or crypto "
            "wallet accounts",
        )

    selected = {r.row_number: r for r in preview.rows if r.row_number in payload.row_numbers}
    # Process buys before sells on a tied date, same reasoning as
    # `compute_holding_positions` — otherwise a same-day sell can look like
    # it's overdrawing a position a later-processed same-day buy would cover.
    ordered = sorted(selected.values(), key=lambda r: (r.date, r.type != "buy"))

    created: list[AssetTransaction] = []
    for row in ordered:
        if not row.is_parsable:
            continue  # silently skip — the frontend shouldn't have sent these anyway

        try:
            asset = asset_prices_service.find_or_create_asset(db, row.symbol, row.asset_type)
        except AssetPriceUnavailable:
            continue  # a partial import beats failing the whole batch on one bad row

        if row.type == "sell":
            held = _current_quantity(db, account.id, asset.id)
            if row.quantity > held:
                continue

        try:
            rate = get_rate(db, asset.currency, current_user.base_currency, row.date)
        except ExchangeRateUnavailable:
            continue

        gross = row.quantity * row.price
        total = gross + row.fee if row.type == "buy" else gross - row.fee

        cash_transaction = _create_linked_cash_transaction(
            db,
            account=account,
            asset=asset,
            asset_transaction_type=row.type,
            total=total,
            rate=rate,
            on_date=row.date,
            source="import",
        )

        transaction = AssetTransaction(
            account_id=row.account_id,
            asset_id=asset.id,
            transaction_id=cash_transaction.id,
            type=row.type,
            quantity=row.quantity,
            price=row.price,
            fee=row.fee,
            amount_base_currency=total * rate,
            exchange_rate=rate,
            date=row.date,
            notes=row.notes,
        )
        # Added inside the loop (not batched at the end) so a later row's
        # `_current_quantity` sees earlier rows from this same import via
        # autoflush — otherwise a multi-row buy-then-sell of a brand-new
        # symbol would look like an overdraw against an empty position.
        db.add(transaction)
        created.append(transaction)

    db.commit()
    for t in created:
        db.refresh(t)

    csv_import_service.discard_asset_preview(payload.import_id)
    return created


@router.get("/net-worth", response_model=NetWorthSummary)
def net_worth(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NetWorthSummary:
    accounts = account_balances(db, current_user)
    holdings = holdings_with_value(db, current_user)
    physical_assets = physical_assets_with_value(db, current_user)
    db.commit()  # persist the price/rate cache rows filled in above

    total_cash_balance = sum((a.balance_base_currency for a in accounts), Decimal("0"))
    total_holdings_value = sum((h.market_value_base_currency for h in holdings), Decimal("0"))
    # An asset that couldn't be priced today counts as nothing rather than
    # failing the whole summary; the asset list still shows it as unpriced.
    total_physical_assets_value = sum(
        (
            a.current_value_base_currency
            for a in physical_assets
            if a.current_value_base_currency is not None
        ),
        Decimal("0"),
    )

    return NetWorthSummary(
        base_currency=current_user.base_currency,
        total_net_worth=total_cash_balance + total_holdings_value + total_physical_assets_value,
        total_cash_balance=total_cash_balance,
        total_holdings_value=total_holdings_value,
        total_physical_assets_value=total_physical_assets_value,
        accounts=accounts,
        holdings=holdings,
        physical_assets=physical_assets,
    )


_PERIOD_DAYS = {
    PortfolioHistoryPeriod.one_month: 30,
    PortfolioHistoryPeriod.three_months: 90,
    PortfolioHistoryPeriod.six_months: 180,
    PortfolioHistoryPeriod.one_year: 365,
}


@router.get("/history", response_model=PortfolioHistoryResponse)
def portfolio_history(
    period: PortfolioHistoryPeriod = PortfolioHistoryPeriod.six_months,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioHistoryResponse:
    today = date_.today()

    asset_transactions = (
        user_asset_transactions_query(db, current_user).order_by(AssetTransaction.date).all()
    )
    cash_transactions = (
        db.query(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.user_id == current_user.id,
            Account.deleted_at.is_(None),
            Transaction.deleted_at.is_(None),
        )
        .order_by(Transaction.date)
        .all()
    )

    # Sold ones too: they were part of net worth until the day they left.
    physical_assets = (
        physical_assets_service.user_physical_assets_query(db, current_user)
        .order_by(PhysicalAsset.purchase_date)
        .all()
    )

    earliest_dates = (
        [tx.date for tx in asset_transactions]
        + [tx.date for tx in cash_transactions]
        + [a.purchase_date for a in physical_assets]
    )
    earliest = min(earliest_dates) if earliest_dates else today

    if period == PortfolioHistoryPeriod.all:
        start_date = earliest
    else:
        start_date = max(earliest, today - timedelta(days=_PERIOD_DAYS[period]))

    assets_by_id: dict[UUID, Asset] = {tx.asset_id: tx.asset for tx in asset_transactions}

    # One historical fetch per asset/currency backfills its entire series —
    # missing data for one asset shouldn't 500 the whole chart, so a fetch
    # failure just means that asset contributes nothing to holdings value.
    price_history: dict[UUID, dict[date_, Decimal]] = {}
    for asset_id, asset in assets_by_id.items():
        try:
            price_history[asset_id] = asset_prices_service.get_price_history(
                db, asset, start_date, today
            )
        except AssetPriceUnavailable:
            price_history[asset_id] = {}

    # Metals price through the seeded `metal` assets, so their history comes
    # from the same backfill as holdings.
    metal_assets: dict[str, Asset] = {}
    for metal in {a.metal for a in physical_assets if a.kind == "metal" and a.metal}:
        metal_asset = physical_assets_service.metal_asset(db, metal)
        if metal_asset is None:
            continue
        metal_assets[metal] = metal_asset
        try:
            price_history[metal_asset.id] = asset_prices_service.get_price_history(
                db, metal_asset, start_date, today
            )
        except AssetPriceUnavailable:
            price_history[metal_asset.id] = {}

    rate_history: dict[str, dict[date_, Decimal]] = {}
    currencies = {asset.currency for asset in assets_by_id.values()}
    currencies |= {asset.currency for asset in metal_assets.values()}
    currencies |= {a.currency for a in physical_assets if a.kind == "vehicle"}
    for currency in currencies:
        if currency == current_user.base_currency:
            continue
        try:
            rate_history[currency] = get_rate_history(
                db, currency, current_user.base_currency, start_date, today
            )
        except ExchangeRateUnavailable:
            rate_history[currency] = {}

    def rate_on(currency: str, on_date: date_) -> Decimal:
        if currency == current_user.base_currency:
            return Decimal("1")
        available = [d for d in rate_history.get(currency, {}) if d <= on_date]
        if available:
            return rate_history[currency][max(available)]
        try:
            return get_rate(db, currency, current_user.base_currency, on_date)
        except ExchangeRateUnavailable:
            return Decimal("1")

    def price_on(asset_id: UUID, on_date: date_) -> Decimal | None:
        series = price_history.get(asset_id, {})
        available = [d for d in series if d <= on_date]
        return series[max(available)] if available else None

    points: list[PortfolioHistoryPoint] = []
    for sample_date in _sample_dates(start_date, today):
        # Transaction.amount_base_currency is already the frozen conversion
        # from the day it happened — reuse it rather than re-converting.
        cash_base = sum(
            (
                Decimal(str(tx.amount_base_currency))
                for tx in cash_transactions
                if tx.date <= sample_date
            ),
            Decimal("0"),
        )

        quantities: dict[UUID, Decimal] = {}
        for tx in asset_transactions:
            if tx.date > sample_date:
                continue
            quantity = Decimal(str(tx.quantity))
            quantities[tx.asset_id] = quantities.get(tx.asset_id, Decimal("0")) + (
                quantity if tx.type == "buy" else -quantity
            )

        holdings_base = Decimal("0")
        for asset_id, quantity in quantities.items():
            if quantity <= 0:
                continue
            price = price_on(asset_id, sample_date)
            if price is None:
                continue
            asset = assets_by_id[asset_id]
            holdings_base += quantity * price * rate_on(asset.currency, sample_date)

        physical_base = Decimal("0")
        for physical_asset in physical_assets:
            if not physical_assets_service.is_held_on(physical_asset, sample_date):
                continue
            if physical_asset.kind == "vehicle":
                physical_base += physical_assets_service.vehicle_value(
                    physical_asset, sample_date
                ) * rate_on(physical_asset.currency, sample_date)
                continue
            metal_asset = metal_assets.get(physical_asset.metal or "")
            spot = price_on(metal_asset.id, sample_date) if metal_asset else None
            if metal_asset is None or spot is None:
                continue
            physical_base += physical_assets_service.metal_value_usd(
                physical_asset, spot
            ) * rate_on(metal_asset.currency, sample_date)

        points.append(
            PortfolioHistoryPoint(
                date=sample_date,
                total_holdings_value_base_currency=holdings_base,
                total_cash_balance_base_currency=cash_base,
                total_physical_assets_value_base_currency=physical_base,
                total_net_worth=cash_base + holdings_base + physical_base,
            )
        )

    db.commit()  # persist the price/rate history cache rows filled in above
    return PortfolioHistoryResponse(base_currency=current_user.base_currency, points=points)
