"""
Balance and holding aggregations shared by the portfolio router and the
planning engine.

These started as private helpers inside `routers/portfolio.py`. They moved
here unchanged when the planning engine needed the same numbers: a survival
budget's "months of runway" is cash-on-hand divided by monthly primary
spend, and phase C's savings goals are funded by mapped accounts. Computing
either from a second, subtly different balance query is how two parts of an
app start disagreeing about how much money there is.
"""

from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from app.models import Account, AssetTransaction, Transaction, User
from app.schemas import AccountBalance, HoldingWithValue
from app.services import asset_prices as asset_prices_service
from app.services.exchange_rates import get_rate


def user_asset_transactions_query(db: Session, user: User):
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


def account_balances(db: Session, user: User) -> list[AccountBalance]:
    """
    Current balance per active account, in both the account's own currency
    and the user's base currency.

    Every transaction counts, `transfer` rows included — an opening balance
    and a portfolio cash leg both genuinely move the balance, unlike the
    income/expense summaries that must exclude them.

    Soft-deleted accounts are dropped: the aggregate below doesn't filter
    them, but the result is built by iterating active accounts, so their
    balances simply never appear. That is right for a net-worth view. It is
    a trap for anything that maps an account to something else (a phase-C
    savings goal): such a mapping must block the account's deletion, or the
    goal silently reads as unfunded.
    """
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


def total_cash_balance(db: Session, user: User) -> Decimal:
    """Cash across every active account, in base currency."""
    return sum(
        (balance.balance_base_currency for balance in account_balances(db, user)),
        Decimal("0"),
    )


def compute_holding_positions(db: Session, user: User) -> dict[tuple[UUID, UUID], dict]:
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
        user_asset_transactions_query(db, user)
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


def holdings_with_value(db: Session, user: User) -> list[HoldingWithValue]:
    """
    Positions priced at today's market value.

    Note for callers outside the portfolio router: this issues a live
    `get_price` + `get_rate` per holding with no batching, and both of those
    services commit the session on a cache miss. Never put it on a read path
    that also writes, and prefer a cash-only route where the extra precision
    isn't needed.
    """
    today = date_.today()
    holdings = []

    for (account_id, asset_id), position in compute_holding_positions(db, user).items():
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
