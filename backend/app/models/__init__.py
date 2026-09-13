"""
SQLAlchemy models for the finance tracker.

Notes:
- Uses SQLAlchemy 2.0 style (Mapped / mapped_column).
- `SoftDeleteMixin` adds `deleted_at`; a default query filter should be applied
  at the repository/service layer (e.g. `.where(Model.deleted_at.is_(None))`)
  rather than relying on callers to remember it every time.
- Money fields use Numeric (maps to Postgres NUMERIC), never Float.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")
    categories: Mapped[list["Category"]] = relationship(back_populates="user")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="user")


# ---------------------------------------------------------------------------
# Currencies (reference table)
# ---------------------------------------------------------------------------

class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)  # e.g. "EUR", "BTC"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    decimal_places: Mapped[int] = mapped_column(default=2, nullable=False)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class Account(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # AccountType enum value
    currency: Mapped[str] = mapped_column(String(3), ForeignKey("currencies.code"), nullable=False)

    user: Mapped["User"] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
    asset_transactions: Mapped[list["AssetTransaction"]] = relationship(back_populates="account")

    __table_args__ = (
        CheckConstraint(
            "type in ('checking','savings','credit_card','investment','crypto_wallet')",
            name="ck_accounts_type",
        ),
    )


# ---------------------------------------------------------------------------
# Categories (self-referential for parent/child)
# ---------------------------------------------------------------------------

class Category(Base, SoftDeleteMixin):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # CategoryType enum value
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="categories")
    parent: Mapped["Category | None"] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="category")

    __table_args__ = (
        CheckConstraint("type in ('expense','income')", name="ck_categories_type"),
    )


# ---------------------------------------------------------------------------
# Transactions (core table, currency-aware)
# ---------------------------------------------------------------------------

class Transaction(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True, index=True
    )

    # Original transaction currency/amount, as it happened.
    amount: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), ForeignKey("currencies.code"), nullable=False)

    # Frozen conversion into the user's base currency at the transaction date —
    # never recomputed later, so historical reports stay stable. See exchange_rate.
    amount_base_currency: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    exchange_rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)

    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # TransactionType enum value
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")

    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category | None"] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint("type in ('expense','income','transfer')", name="ck_transactions_type"),
        CheckConstraint("source in ('manual','import')", name="ck_transactions_source"),
    )


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

class Budget(Base, SoftDeleteMixin):
    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categories.id"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # BudgetPeriod enum value
    amount_limit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)

    user: Mapped["User"] = relationship(back_populates="budgets")
    category: Mapped["Category"] = relationship(back_populates="budgets")

    __table_args__ = (
        CheckConstraint("period in ('monthly','yearly')", name="ck_budgets_period"),
    )


# ---------------------------------------------------------------------------
# Assets / Asset transactions / Prices (phase 3 — portfolio tracker)
# ---------------------------------------------------------------------------

class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(10), nullable=False)  # stock/etf/crypto
    currency: Mapped[str] = mapped_column(String(3), ForeignKey("currencies.code"), nullable=False)

    asset_transactions: Mapped[list["AssetTransaction"]] = relationship(back_populates="asset")
    prices: Mapped[list["AssetPrice"]] = relationship(back_populates="asset")

    __table_args__ = (
        UniqueConstraint("symbol", "asset_type", name="uq_assets_symbol_type"),
        CheckConstraint("asset_type in ('stock','etf','crypto')", name="ck_assets_type"),
    )


class AssetPrice(Base):
    __tablename__ = "asset_prices"

    id: Mapped[uuid.UUID] = uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True
    )
    price: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)

    asset: Mapped["Asset"] = relationship(back_populates="prices")

    __table_args__ = (
        UniqueConstraint("asset_id", "date", name="uq_asset_prices_asset_date"),
    )


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------

class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[uuid.UUID] = uuid_pk()
    from_currency: Mapped[str] = mapped_column(String(3), ForeignKey("currencies.code"), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(3), ForeignKey("currencies.code"), nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint("from_currency", "to_currency", "date", name="uq_exchange_rates_pair_date"),
    )

from app.models.asset_transaction import AssetTransaction  # noqa: F401,E402
from app.models.refresh_token import RefreshToken  # noqa: F401
