"""
Portfolio endpoints: holdings CRUD, asset search, and net worth.

One combined router rather than separate `assets.py` / `holdings.py` files:
`Asset` has no standalone CRUD from a user's perspective — it's resolved
implicitly the same way `Currency` is, never independently created/edited by
a user — and prices/holdings/net-worth are inseparable from each other the
same way CSV import lives inside `transactions.py` instead of its own file.
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from app.deps import get_current_user, get_db
from app.models import Account, Asset, AssetTransaction, Transaction, User
from app.schemas import (
    AccountBalance,
    AssetSearchResult,
    AssetTransactionCreate,
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
from app.services.asset_prices import AssetPriceUnavailable
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate, get_rate_history

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


def _get_owned_account_or_404(db: Session, account_id: UUID, user: User) -> Account:
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == user.id, Account.deleted_at.is_(None))
        .first()
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


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


def _user_asset_transactions_query(db: Session, user: User):
    return (
        db.query(AssetTransaction)
        .join(Account, Account.id == AssetTransaction.account_id)
        .options(joinedload(AssetTransaction.asset))
        .filter(
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
            AssetTransaction.deleted_at.is_(None),
        )
    )


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


def _compute_holding_positions(db: Session, user: User) -> dict[tuple[UUID, UUID], dict]:
    """
    Aggregate every non-deleted AssetTransaction into a live position per
    (account_id, asset_id) using weighted-average cost. Realized P&L on a
    sell depends on the average cost of every prior buy, so — unlike every
    other aggregation in this app — this has to be a sequential walk in
    Python rather than a SQL GROUP BY.

    `date` has day granularity (no time-of-day), so same-day buys and sells
    tie on it — `created_at` alone isn't a safe tiebreaker either, since
    requests issued in the same wall-clock instant (or the same DB
    transaction, as in tests) can carry an identical timestamp. Explicitly
    ordering buys before sells on a tied date is the only interpretation
    that can't spuriously "sell" from a position that's still at zero.
    """
    buy_before_sell = case((AssetTransaction.type == "buy", 0), else_=1)
    transactions = (
        _user_asset_transactions_query(db, user)
        .order_by(AssetTransaction.date, buy_before_sell, AssetTransaction.created_at)
        .all()
    )

    positions: dict[tuple[UUID, UUID], dict] = {}
    for tx in transactions:
        key = (tx.account_id, tx.asset_id)
        position = positions.setdefault(
            key,
            {
                "account_id": tx.account_id,
                "asset": tx.asset,
                "quantity": Decimal("0"),
                "cost_basis": Decimal("0"),
                "realized_pnl": Decimal("0"),
            },
        )
        quantity = Decimal(str(tx.quantity))
        price = Decimal(str(tx.price))
        fee = Decimal(str(tx.fee))

        if tx.type == "buy":
            position["cost_basis"] += quantity * price + fee
            position["quantity"] += quantity
        else:
            held = position["quantity"]
            avg_cost = position["cost_basis"] / held if held else Decimal("0")
            position["realized_pnl"] += (price - avg_cost) * quantity - fee
            position["cost_basis"] -= avg_cost * quantity
            position["quantity"] -= quantity

    return positions


def _holdings_with_value(db: Session, user: User) -> list[HoldingWithValue]:
    today = date_.today()
    holdings = []

    for (account_id, asset_id), position in _compute_holding_positions(db, user).items():
        if position["quantity"] <= 0:
            continue

        asset = position["asset"]
        quantity = position["quantity"]
        avg_buy_price = position["cost_basis"] / quantity
        price = asset_prices_service.get_price(db, asset, today)

        market_value = quantity * price
        market_value_base_currency = market_value * get_rate(
            db, asset.currency, user.base_currency, today
        )
        cost_basis = position["cost_basis"]
        unrealized_pnl = market_value - cost_basis
        unrealized_pnl_percentage = float(unrealized_pnl / cost_basis * 100) if cost_basis else 0.0

        holdings.append(
            HoldingWithValue(
                id=f"{account_id}:{asset_id}",
                account_id=account_id,
                asset=asset,
                quantity=quantity,
                avg_buy_price=avg_buy_price,
                realized_pnl=position["realized_pnl"],
                current_price=price,
                price_date=today,
                market_value=market_value,
                market_value_base_currency=market_value_base_currency,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_percentage=round(unrealized_pnl_percentage, 2),
            )
        )

    return holdings


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


def _account_balances(db: Session, user: User) -> list[AccountBalance]:
    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id, Account.deleted_at.is_(None))
        .all()
    )

    rows = (
        db.query(
            Transaction.account_id,
            func.sum(Transaction.amount).label("balance"),
            func.sum(Transaction.amount_base_currency).label("balance_base_currency"),
        )
        .join(Account, Account.id == Transaction.account_id)
        .filter(Account.user_id == user.id, Transaction.deleted_at.is_(None))
        .group_by(Transaction.account_id)
        .all()
    )
    balance_by_account: dict[UUID, tuple[Decimal, Decimal]] = {
        row._mapping["account_id"]: (
            Decimal(str(row._mapping["balance"])),
            Decimal(str(row._mapping["balance_base_currency"])),
        )
        for row in rows
    }
    zero_balance = (Decimal("0"), Decimal("0"))

    return [
        AccountBalance(
            account_id=account.id,
            account_name=account.name,
            currency=account.currency,
            balance=balance_by_account.get(account.id, zero_balance)[0],
            balance_base_currency=balance_by_account.get(account.id, zero_balance)[1],
        )
        for account in accounts
    ]


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
    return _holdings_with_value(db, current_user)


@router.get("/transactions", response_model=list[AssetTransactionSchema])
def list_asset_transactions(
    account_id: UUID | None = None,
    asset_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AssetTransaction]:
    query = _user_asset_transactions_query(db, current_user)
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
    account = _get_owned_account_or_404(db, payload.account_id, current_user)
    if account.type not in ("investment", "crypto_wallet"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Asset transactions can only be logged on investment or crypto wallet accounts",
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

    transaction = AssetTransaction(
        account_id=account.id,
        asset_id=asset.id,
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
    db.commit()


@router.get("/net-worth", response_model=NetWorthSummary)
def net_worth(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NetWorthSummary:
    accounts = _account_balances(db, current_user)
    holdings = _holdings_with_value(db, current_user)

    total_cash_balance = sum((a.balance_base_currency for a in accounts), Decimal("0"))
    total_holdings_value = sum((h.market_value_base_currency for h in holdings), Decimal("0"))

    return NetWorthSummary(
        base_currency=current_user.base_currency,
        total_net_worth=total_cash_balance + total_holdings_value,
        total_cash_balance=total_cash_balance,
        total_holdings_value=total_holdings_value,
        accounts=accounts,
        holdings=holdings,
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
        _user_asset_transactions_query(db, current_user).order_by(AssetTransaction.date).all()
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

    earliest_dates = [tx.date for tx in asset_transactions] + [tx.date for tx in cash_transactions]
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

    rate_history: dict[str, dict[date_, Decimal]] = {}
    for currency in {asset.currency for asset in assets_by_id.values()}:
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

        points.append(
            PortfolioHistoryPoint(
                date=sample_date,
                total_holdings_value_base_currency=holdings_base,
                total_cash_balance_base_currency=cash_base,
                total_net_worth=cash_base + holdings_base,
            )
        )

    return PortfolioHistoryResponse(base_currency=current_user.base_currency, points=points)
