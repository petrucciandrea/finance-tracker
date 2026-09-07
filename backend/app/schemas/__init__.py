"""
Pydantic schemas for the finance tracker API.

Convention:
- `*Create` / `*Update` schemas are used as request bodies.
- Plain schemas (no suffix) are used as response bodies and read from ORM objects
  (model_config = ConfigDict(from_attributes=True)).
- Enums are shared between request/response schemas and SQLAlchemy models.
"""

from datetime import date as date_, datetime
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
    group_by: list[SummaryGroupBy] = Field(default_factory=lambda: [SummaryGroupBy.month])
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
