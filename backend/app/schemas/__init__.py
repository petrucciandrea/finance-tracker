"""
Pydantic schemas for the finance tracker API.

Convention:
- `*Create` / `*Update` schemas are used as request bodies.
- Plain schemas (no suffix) are used as response bodies and read from ORM objects
  (model_config = ConfigDict(from_attributes=True)).
- Enums are shared between request/response schemas and SQLAlchemy models.
"""

from datetime import date as date_
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AccountType(str, Enum):
    checking = "checking"
    savings = "savings"
    credit_card = "credit_card"
    investment = "investment"
    crypto_wallet = "crypto_wallet"


class CategoryType(str, Enum):
    expense = "expense"
    income = "income"
    transfer = "transfer"


class NecessityLevel(str, Enum):
    """
    How essential a kind of spend is. Deliberately separate from savings:
    the allocation model's fourth bucket is what is *not* spent, so it has
    no necessity level of its own.
    """

    primary = "primary"
    useful = "useful"
    discretionary = "discretionary"


class AllocationBucket(str, Enum):
    """
    The four slots income is split into. The first three mirror
    NecessityLevel; `savings` is the residual — what wasn't spent — so it
    has no necessity level of its own and never appears on a category.
    """

    primary = "primary"
    useful = "useful"
    discretionary = "discretionary"
    savings = "savings"


class TransactionType(str, Enum):
    expense = "expense"
    income = "income"
    transfer = "transfer"


class TransactionSource(str, Enum):
    manual = "manual"
    import_ = "import"


class BudgetPeriod(str, Enum):
    monthly = "monthly"
    yearly = "yearly"


class AssetType(str, Enum):
    stock = "stock"
    etf = "etf"
    crypto = "crypto"


class SummaryGroupBy(str, Enum):
    category = "category"
    month = "month"


# ---------------------------------------------------------------------------
# Shared / base
# ---------------------------------------------------------------------------

class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Auth / Users
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    base_currency: str = Field(min_length=3, max_length=3, description="ISO 4217 code, e.g. EUR")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    base_currency: str | None = Field(
        default=None, min_length=3, max_length=3, description="ISO 4217 code, e.g. EUR"
    )
    # Anagrafica — all optional and independently clearable (send `null` to
    # clear one without touching the others), unlike email/base_currency
    # which a PATCH is never meant to unset.
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date_ | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class User(ORMBase):
    id: UUID
    email: EmailStr
    base_currency: str
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date_ | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: AccountType
    currency: str = Field(min_length=3, max_length=3)
    starting_balance: Decimal | None = Field(default=None, max_digits=18, decimal_places=8)


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: AccountType | None = None


class Account(ORMBase):
    id: UUID
    name: str
    type: AccountType
    currency: str
    created_at: datetime
    deleted_at: datetime | None = None


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: CategoryType
    parent_id: UUID | None = None
    # Expense categories only (422 otherwise). None means "not classified";
    # a subcategory left None inherits its parent's level at read time.
    necessity_level: NecessityLevel | None = None
    # Income categories only (422 otherwise).
    excluded_from_income_base: bool = False


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: UUID | None = None
    necessity_level: NecessityLevel | None = None
    excluded_from_income_base: bool | None = None


class Category(ORMBase):
    id: UUID
    name: str
    type: CategoryType
    parent_id: UUID | None = None
    necessity_level: NecessityLevel | None = None
    excluded_from_income_base: bool = False
    deleted_at: datetime | None = None


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

class TransactionCreate(BaseModel):
    account_id: UUID
    category_id: UUID | None = None
    amount: Decimal = Field(max_digits=18, decimal_places=8)
    currency: str = Field(min_length=3, max_length=3)
    date: date_
    description: str | None = Field(default=None, max_length=500)
    type: TransactionType
    # Overrides the category's (or its parent's) level for this one row.
    necessity_level_override: NecessityLevel | None = None


class TransactionUpdate(BaseModel):
    category_id: UUID | None = None
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=8)
    date: date_ | None = None
    description: str | None = Field(default=None, max_length=500)
    necessity_level_override: NecessityLevel | None = None


class Transaction(ORMBase):
    id: UUID
    account_id: UUID
    category_id: UUID | None = None
    amount: Decimal
    currency: str
    amount_base_currency: Decimal
    exchange_rate: Decimal
    date: date_
    description: str | None = None
    type: TransactionType
    source: TransactionSource
    necessity_level_override: NecessityLevel | None = None
    created_at: datetime
    deleted_at: datetime | None = None


class TransactionListParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    date_from: date_ | None = None
    date_to: date_ | None = None
    category_id: UUID | None = None
    account_id: UUID | None = None
    currency: str | None = None
    type: TransactionType | None = None


class TransactionListResponse(BaseModel):
    data: list[Transaction]
    meta: PaginationMeta


# --- Import flow ---

class TransactionImportRow(BaseModel):
    row_number: int
    account_id: UUID
    date: date_
    amount: Decimal
    currency: str
    description: str | None = None
    suggested_category_id: UUID | None = None
    is_duplicate: bool = False
    is_parsable: bool = True
    error: str | None = None


class TransactionImportPreview(BaseModel):
    import_id: UUID
    rows: list[TransactionImportRow]
    total_rows: int
    parsable_rows: int
    duplicate_rows: int


class TransactionImportConfirm(BaseModel):
    import_id: UUID
    row_numbers: list[int] = Field(description="Rows to actually commit, e.g. excluding duplicates")


# --- Summary ---

class TransactionSummaryParams(BaseModel):
    group_by: list[SummaryGroupBy] | None = None
    date_from: date_ | None = None
    date_to: date_ | None = None
    currency: str | None = None


class TransactionSummaryItem(BaseModel):
    month: str | None = None  # "YYYY-MM", present when grouping includes month
    category_id: UUID | None = None
    category_name: str | None = None
    total_amount_base_currency: Decimal
    transaction_count: int


class TransactionSummaryResponse(BaseModel):
    data: list[TransactionSummaryItem]


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

class BudgetCreate(BaseModel):
    category_id: UUID
    period: BudgetPeriod
    amount_limit: Decimal = Field(max_digits=18, decimal_places=2)
    start_date: date_


class BudgetUpdate(BaseModel):
    # Only amount_limit is patchable, deliberately. `budgets_status()` derives
    # period boundaries from `start_date`/`period` and spend from a live join
    # on `category_id` — retroactively changing any of those would silently
    # recompute historical `amount_spent` under different rules than when it
    # was recorded. To change period/category, soft-delete and create a new
    # budget instead; the old one's historical status stays intact.
    amount_limit: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)


class Budget(ORMBase):
    id: UUID
    category_id: UUID
    period: BudgetPeriod
    amount_limit: Decimal
    start_date: date_
    deleted_at: datetime | None = None


class BudgetStatus(BaseModel):
    category_id: UUID
    category_name: str
    period: BudgetPeriod
    amount_limit: Decimal
    amount_spent: Decimal
    percentage_used: float
    is_over_budget: bool


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------

class ExchangeRate(ORMBase):
    from_currency: str
    to_currency: str
    rate: Decimal
    date: date_
    source: str


# ---------------------------------------------------------------------------
# Portfolio (assets, holdings, net worth)
# ---------------------------------------------------------------------------

class Asset(ORMBase):
    id: UUID
    symbol: str
    name: str
    asset_type: AssetType
    currency: str


class AssetSearchResult(BaseModel):
    symbol: str
    name: str
    asset_type: AssetType


class AssetTransactionType(str, Enum):
    buy = "buy"
    sell = "sell"


class AssetTransactionCreate(BaseModel):
    account_id: UUID
    symbol: str = Field(min_length=1, max_length=20)
    asset_type: AssetType
    type: AssetTransactionType
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    price: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    fee: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=8)
    date: date_
    notes: str | None = Field(default=None, max_length=500)


class AssetTransactionUpdate(BaseModel):
    # `type` and the resolved asset are immutable after creation — same
    # convention as `currency` never being patchable on TransactionUpdate.
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    price: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=8)
    fee: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=8)
    date: date_ | None = None
    notes: str | None = Field(default=None, max_length=500)


class AssetTransaction(ORMBase):
    id: UUID
    account_id: UUID
    asset: Asset
    type: AssetTransactionType
    quantity: Decimal
    price: Decimal
    fee: Decimal
    amount_base_currency: Decimal
    exchange_rate: Decimal
    date: date_
    notes: str | None = None
    created_at: datetime
    deleted_at: datetime | None = None


class AssetTransactionImportRow(BaseModel):
    row_number: int
    account_id: UUID
    symbol: str
    asset_type: AssetType
    type: AssetTransactionType
    quantity: Decimal
    price: Decimal
    fee: Decimal
    date: date_
    notes: str | None = None
    is_duplicate: bool = False
    is_parsable: bool = True
    error: str | None = None


class AssetTransactionImportPreview(BaseModel):
    import_id: UUID
    rows: list[AssetTransactionImportRow]
    total_rows: int
    parsable_rows: int
    duplicate_rows: int


class AssetTransactionImportConfirm(BaseModel):
    import_id: UUID
    row_numbers: list[int] = Field(description="Rows to actually commit, e.g. excluding duplicates")


class HoldingWithValue(BaseModel):
    # Not backed by its own DB row anymore — computed from AssetTransaction
    # history, so `id` is synthesized for a stable React key / URL rather
    # than being a real primary key.
    id: str
    account_id: UUID
    asset: Asset
    quantity: Decimal
    avg_buy_price: Decimal  # weighted-average cost of currently-held units
    realized_pnl: Decimal  # cumulative realized P&L from sells, in asset currency
    current_price: Decimal
    price_date: date_
    market_value: Decimal  # quantity * current_price, in asset.currency
    market_value_base_currency: Decimal  # converted via get_rate()
    unrealized_pnl: Decimal  # market_value - (quantity * avg_buy_price), in asset.currency
    unrealized_pnl_percentage: float


class AccountBalance(BaseModel):
    account_id: UUID
    account_name: str
    currency: str
    balance: Decimal
    balance_base_currency: Decimal


class NetWorthSummary(BaseModel):
    base_currency: str
    total_net_worth: Decimal
    total_cash_balance: Decimal
    total_holdings_value: Decimal
    accounts: list[AccountBalance]
    holdings: list[HoldingWithValue]


class PortfolioHistoryPeriod(str, Enum):
    one_month = "1m"
    three_months = "3m"
    six_months = "6m"
    one_year = "1y"
    all = "all"


class PortfolioHistoryPoint(BaseModel):
    date: date_
    total_holdings_value_base_currency: Decimal
    total_cash_balance_base_currency: Decimal
    total_net_worth: Decimal


class PortfolioHistoryResponse(BaseModel):
    base_currency: str
    points: list[PortfolioHistoryPoint]


# ---------------------------------------------------------------------------
# Planning — allocation plan, status, survival budget, simulator
# ---------------------------------------------------------------------------

class AllocationPlan(ORMBase):
    id: UUID
    pct_primary: Decimal
    pct_useful: Decimal
    pct_discretionary: Decimal
    pct_savings: Decimal
    lookback_months: int
    default_source_account_id: UUID | None = None


class AllocationPlanUpdate(BaseModel):
    """
    All four percentages move together or not at all: the database enforces
    that they sum to 100, so a partial update could only ever fail. The
    router rejects a partial set with a message saying so, rather than
    letting a CheckConstraint violation surface as a generic 500.
    """

    pct_primary: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    pct_useful: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    pct_discretionary: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    pct_savings: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    lookback_months: int | None = Field(default=None, ge=1, le=60)
    default_source_account_id: UUID | None = None


class AllocationBucketStatus(BaseModel):
    bucket: AllocationBucket
    percentage: Decimal
    target_amount: Decimal
    actual_amount: Decimal
    # target - actual. Positive means "under target", which is good for the
    # three spend buckets and bad for `savings` — the bucket is named, so
    # the client decides how to colour it rather than the API guessing.
    deviation: Decimal
    percentage_used: float
    is_over_target: bool


class IncomeCategoryBreakdown(BaseModel):
    category_id: UUID | None = None
    category_name: str | None = None
    excluded_from_income_base: bool
    total_amount_base_currency: Decimal


class AllocationStatus(BaseModel):
    base_currency: str
    period_start: date_
    period_end: date_
    income_total: Decimal
    buckets: list[AllocationBucketStatus]
    # Spend whose category (and its parent) carry no necessity level. Kept
    # out of the buckets on purpose: folding it into `primary` would make an
    # unclassified account look like a disciplined one.
    unclassified_amount: Decimal
    classification_coverage: float
    income_breakdown: list[IncomeCategoryBreakdown]


class SurvivalBudget(BaseModel):
    base_currency: str
    lookback_months: int
    # Complete months actually used for the average — smaller than
    # lookback_months for a user whose history is shorter.
    months_analysed: int
    # None, never zero, when there isn't a single complete month of history.
    # Zero would read as "you need nothing to live on", which would in turn
    # mark a dynamic emergency-fund target as already met.
    monthly_primary_expenses: Decimal | None = None
    monthly_total_expenses: Decimal | None = None
    monthly_income: Decimal | None = None
    total_cash_balance: Decimal
    # Cash divided by the survival budget. None whenever the survival budget
    # is unknown or zero.
    months_of_runway: float | None = None


class SimulationCut(BaseModel):
    """
    One "what if I cut this" lever. Exactly one of `necessity_level` or
    `category_id` must be set; the router rejects both or neither.
    """

    necessity_level: NecessityLevel | None = None
    category_id: UUID | None = None
    cut_percentage: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class SimulationRequest(BaseModel):
    date: date_ | None = None
    cuts: list[SimulationCut] = Field(default_factory=list)


class SimulatedBucket(BaseModel):
    bucket: AllocationBucket
    baseline_amount: Decimal
    simulated_amount: Decimal
    freed_amount: Decimal


class SimulationResponse(BaseModel):
    base_currency: str
    period_start: date_
    period_end: date_
    income_total: Decimal
    buckets: list[SimulatedBucket]
    total_baseline_spend: Decimal
    total_simulated_spend: Decimal
    total_freed: Decimal
    baseline_savings_amount: Decimal
    simulated_savings_amount: Decimal
    baseline_savings_rate: float
    simulated_savings_rate: float
    baseline_survival_budget: Decimal | None = None
    # The survival budget with the same cuts applied to the historical
    # primary average — i.e. "if you made these cuts permanent". An
    # approximation, and labelled as one in the UI.
    simulated_survival_budget: Decimal | None = None
