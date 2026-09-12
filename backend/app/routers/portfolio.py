"""
Portfolio endpoints: holdings CRUD, asset search, and net worth.

One combined router rather than separate `assets.py` / `holdings.py` files:
`Asset` has no standalone CRUD from a user's perspective — it's resolved
implicitly the same way `Currency` is, never independently created/edited by
a user — and prices/holdings/net-worth are inseparable from each other the
same way CSV import lives inside `transactions.py` instead of its own file.
"""

from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.deps import get_current_user, get_db
from app.models import Account, Holding, Transaction, User
from app.schemas import (
    AccountBalance,
    AssetSearchResult,
    AssetType,
    HoldingCreate,
    HoldingUpdate,
    HoldingWithValue,
    NetWorthSummary,
)
from app.services import asset_prices as asset_prices_service
from app.services.asset_prices import AssetPriceUnavailable
from app.services.exchange_rates import get_rate

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


def _get_owned_holding(db: Session, holding_id: UUID, user: User) -> Holding:
    holding = (
        db.query(Holding)
        .join(Account, Account.id == Holding.account_id)
        .filter(
            Holding.id == holding_id, Account.user_id == user.id, Account.deleted_at.is_(None)
        )
        .first()
    )
    if holding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    return holding


def _holding_with_value(db: Session, holding: Holding, user: User) -> HoldingWithValue:
    today = date_.today()
    price = asset_prices_service.get_price(db, holding.asset, today)

    market_value = holding.quantity * price
    market_value_base_currency = market_value * get_rate(
        db, holding.asset.currency, user.base_currency, today
    )
    cost_basis = holding.quantity * holding.avg_buy_price
    unrealized_pnl = market_value - cost_basis
    unrealized_pnl_percentage = float(unrealized_pnl / cost_basis * 100) if cost_basis else 0.0

    return HoldingWithValue(
        id=holding.id,
        account_id=holding.account_id,
        asset=holding.asset,
        quantity=holding.quantity,
        avg_buy_price=holding.avg_buy_price,
        created_at=holding.created_at,
        current_price=price,
        price_date=today,
        market_value=market_value,
        market_value_base_currency=market_value_base_currency,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_percentage=round(unrealized_pnl_percentage, 2),
    )


def _holdings_with_value(db: Session, user: User) -> list[HoldingWithValue]:
    holdings = (
        db.query(Holding)
        .join(Account, Account.id == Holding.account_id)
        .options(joinedload(Holding.asset))
        .filter(Account.user_id == user.id, Account.deleted_at.is_(None))
        .all()
    )
    return [_holding_with_value(db, holding, user) for holding in holdings]


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


@router.post("/holdings", response_model=HoldingWithValue, status_code=status.HTTP_201_CREATED)
def create_holding(
    payload: HoldingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HoldingWithValue:
    account = _get_owned_account_or_404(db, payload.account_id, current_user)
    if account.type not in ("investment", "crypto_wallet"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Holdings can only be added to investment or crypto wallet accounts",
        )

    asset = asset_prices_service.find_or_create_asset(db, payload.symbol, payload.asset_type.value)

    try:
        asset_prices_service.get_price(db, asset, date_.today())
    except AssetPriceUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    holding = Holding(
        account_id=account.id,
        asset_id=asset.id,
        quantity=payload.quantity,
        avg_buy_price=payload.avg_buy_price,
    )
    db.add(holding)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A holding for this asset already exists in this account — update it instead",
        ) from exc
    db.refresh(holding)

    return _holding_with_value(db, holding, current_user)


@router.patch("/holdings/{holding_id}", response_model=HoldingWithValue)
def update_holding(
    holding_id: UUID,
    payload: HoldingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HoldingWithValue:
    holding = _get_owned_holding(db, holding_id, current_user)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(holding, field, value)
    db.commit()
    db.refresh(holding)
    return _holding_with_value(db, holding, current_user)


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(
    holding_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    # Hard delete, deliberately: a holding is a live position, not a
    # historical event like a transaction, and Holding has no `deleted_at`
    # column — there's no audit value in a "soft-deleted" position.
    holding = _get_owned_holding(db, holding_id, current_user)
    db.delete(holding)
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
