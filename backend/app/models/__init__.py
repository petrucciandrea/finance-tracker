"""
SQLAlchemy models for the finance tracker.

Notes:
- Uses SQLAlchemy 2.0 style (Mapped / mapped_column).
- `SoftDeleteMixin` adds `deleted_at`; a default query filter should be applied
  at the repository/service layer (e.g. `.where(Model.deleted_at.is_(None))`)
  rather than relying on callers to remember it every time.
- Money fields use Numeric (maps to Postgres NUMERIC), never Float, and are
  annotated Mapped[Decimal] to match what SQLAlchemy actually hands back.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    false,
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
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")
    categories: Mapped[list["Category"]] = relationship(back_populates="user")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="user")
    allocation_plans: Mapped[list["AllocationPlan"]] = relationship(back_populates="user")
    savings_goals: Mapped[list["SavingsGoal"]] = relationship(back_populates="user")


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

    # How essential this kind of spend is, for the planning engine's
    # 50/25/15/10 split. NULL means "not classified yet" and is reported as
    # its own bucket — never silently folded into 'primary', which would
    # inflate the survival budget and the emergency-fund target in a way
    # that looks plausible. Expense categories only.
    # Note this is retroactive by construction: `parent_id` is patchable, so
    # re-parenting a subcategory rewrites past bucket reports through the
    # inheritance chain. Same prospective nature as the allocation plan.
    necessity_level: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Income categories only. CSV import types rows purely by sign (see
    # routers/transactions.py), so refunds, reversals and cashback all land
    # as `income`. Left uncorrected they inflate the denominator of the
    # allocation model and the savings quota with it.
    excluded_from_income_base: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    user: Mapped["User"] = relationship(back_populates="categories")
    parent: Mapped["Category | None"] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="category")

    __table_args__ = (
        CheckConstraint("type in ('expense','income','transfer')", name="ck_categories_type"),
        CheckConstraint(
            "necessity_level in ('primary','useful','discretionary')",
            name="ck_categories_necessity_level",
        ),
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
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), ForeignKey("currencies.code"), nullable=False)

    # Frozen conversion into the user's base currency at the transaction date —
    # never recomputed later, so historical reports stay stable. See exchange_rate.
    amount_base_currency: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)

    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # TransactionType enum value
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")

    # Per-transaction exception to the category's necessity level — e.g. a
    # "Ristoranti" charge that was actually a work dinner. Wins over both the
    # category's own level and the one inherited from its parent.
    necessity_level_override: Mapped[str | None] = mapped_column(String(20), nullable=True)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category | None"] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint("type in ('expense','income','transfer')", name="ck_transactions_type"),
        CheckConstraint("source in ('manual','import')", name="ck_transactions_source"),
        CheckConstraint(
            "necessity_level_override in ('primary','useful','discretionary')",
            name="ck_transactions_necessity_level_override",
        ),
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
    amount_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)

    user: Mapped["User"] = relationship(back_populates="budgets")
    category: Mapped["Category"] = relationship(back_populates="budgets")

    __table_args__ = (
        CheckConstraint("period in ('monthly','yearly')", name="ck_budgets_period"),
    )


# ---------------------------------------------------------------------------
# Allocation plan (planning engine — how income should be split)
# ---------------------------------------------------------------------------

class AllocationPlan(Base, TimestampMixin, SoftDeleteMixin):
    """
    The user's income-split model, preset to 50/25/15/10.

    One live plan per user, but deliberately with NO unique index on
    `user_id`: the plan is get-or-created on first read, and a unique index
    would turn two concurrent first reads into an IntegrityError surfacing
    as a generic 500. The "Varie" category get-or-create works precisely
    because a duplicate row is harmless. Callers take the oldest surviving
    row, which is deterministic whether or not a race ever happened.

    Unlike `Budget`, which freezes everything except its limit, this is
    deliberately mutable. A budget is a historical commitment ("in July my
    limit was 200"); a plan is prospective ("this is how I want income
    split now"), so editing the percentages *should* change how the current
    period reads. The flip side is that it also changes how past periods
    read — which is the honest behaviour for a planning tool, and is called
    out in the API docs rather than hidden.
    """

    __tablename__ = "allocation_plans"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    pct_primary: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    pct_useful: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    pct_discretionary: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    pct_savings: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    # How many complete months the primary-expense average looks back over.
    # Feeds both the survival budget and phase C's dynamic emergency-fund
    # target, so it is a plan-level setting rather than a query parameter.
    lookback_months: Mapped[int] = mapped_column(
        Integer, nullable=False, default=6, server_default="6"
    )

    # The account income lands on — the source leg of any suggested
    # transfer. Without it the waterfall can only advise, not propose an
    # executable giroconto.
    default_source_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="allocation_plans")

    __table_args__ = (
        CheckConstraint(
            "pct_primary + pct_useful + pct_discretionary + pct_savings = 100",
            name="ck_allocation_plans_percentages_sum",
        ),
        CheckConstraint("lookback_months between 1 and 60", name="ck_allocation_plans_lookback"),
    )


# ---------------------------------------------------------------------------
# Savings goals (planning engine — the rungs of the waterfall)
# ---------------------------------------------------------------------------

class SavingsGoal(Base, TimestampMixin, SoftDeleteMixin):
    """
    One rung of the savings ladder. The savings quota fills rungs in
    `priority` order and only spills into the next once the one above is
    full, which is what makes the emergency fund refill itself: drain it
    and its gap reopens, putting it back at the top with no special case.

    There is deliberately no unique index on (user_id, priority) — see the
    migration for why swapping two priorities could never satisfy one.
    Ordering is (priority, created_at), deterministic even on a tie.
    """

    __tablename__ = "savings_goals"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)

    target_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    # `months_of_primary_expenses` only: the multiplier on average monthly
    # primary spend (4 / 8 / 12 or anything else). Makes the target move
    # with the user's actual cost of living instead of a fixed number that
    # silently goes stale.
    target_months: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    # `fixed_amount` only.
    target_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    user: Mapped["User"] = relationship(back_populates="savings_goals")
    sources: Mapped[list["SavingsGoalSource"]] = relationship(back_populates="goal")

    __table_args__ = (
        CheckConstraint(
            "kind in ('emergency_fund','medium_term','long_term')",
            name="ck_savings_goals_kind",
        ),
        CheckConstraint(
            "target_mode in ('months_of_primary_expenses','fixed_amount','open_ended')",
            name="ck_savings_goals_target_mode",
        ),
        CheckConstraint(
            "(target_mode = 'months_of_primary_expenses'"
            "  AND target_months IS NOT NULL AND target_amount IS NULL)"
            " OR (target_mode = 'fixed_amount'"
            "  AND target_amount IS NOT NULL AND target_months IS NULL)"
            " OR (target_mode = 'open_ended'"
            "  AND target_months IS NULL AND target_amount IS NULL)",
            name="ck_savings_goals_target_parameters",
        ),
        CheckConstraint("priority >= 0", name="ck_savings_goals_priority"),
    )


class SavingsGoalSource(Base, TimestampMixin, SoftDeleteMixin):
    """
    An account whose balance counts toward a goal.

    Accounts only, not assets: valuing a holding means a live price and FX
    call per position, which would put N external requests behind a plain
    GET of the waterfall. An asset-backed rung is a later phase, and its
    right grain is (account, asset) rather than the globally-shared asset
    row.

    An account may fund at most one goal, or its balance would be counted
    twice over. That rule's scope is the user rather than the goal, so it
    can't be a unique index here and lives in the router as a 409.
    """

    __tablename__ = "savings_goal_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    goal_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("savings_goals.id"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )

    goal: Mapped["SavingsGoal"] = relationship(back_populates="sources")
    account: Mapped["Account"] = relationship()


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
    price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
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
    from_currency: Mapped[str] = mapped_column(
        String(3), ForeignKey("currencies.code"), nullable=False
    )
    to_currency: Mapped[str] = mapped_column(
        String(3), ForeignKey("currencies.code"), nullable=False
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "from_currency", "to_currency", "date", name="uq_exchange_rates_pair_date"
        ),
    )

from app.models.asset_transaction import AssetTransaction  # noqa: F401,E402
from app.models.refresh_token import RefreshToken  # noqa: F401,E402
