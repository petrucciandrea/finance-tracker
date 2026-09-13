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


class User(ORMBase):
    id: UUID
    email: EmailStr
    base_currency: str
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


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: UUID | None = None


class Category(ORMBase):
    id: UUID
    name: str
    type: CategoryType
    parent_id: UUID | None = None
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


class TransactionUpdate(BaseModel):
    category_id: UUID | None = None
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=8)
    date: date_ | None = None
    description: str | None = Field(default=None, max_length=500)


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
