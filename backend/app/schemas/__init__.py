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
    # Physical cash. Just another account: an ATM withdrawal is a giroconto
    # from the bank account into it, cash spending is an expense on it.
    cash = "cash"


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


class SavingsGoalKind(str, Enum):
    emergency_fund = "emergency_fund"
    medium_term = "medium_term"
    long_term = "long_term"


class TargetMode(str, Enum):
    # Target = average monthly primary spend x target_months. Moves with
    # the user's real cost of living instead of going stale.
    months_of_primary_expenses = "months_of_primary_expenses"
    fixed_amount = "fixed_amount"
    # No target: absorbs whatever is left and ends the cascade. The PAC /
    # pension rung at the bottom of the ladder.
    open_ended = "open_ended"


class WaterfallActionKind(str, Enum):
    # A giroconto the backend can actually execute in phase D.
    transfer = "transfer"
    # Something to do by hand — no source account configured, mismatched
    # currencies, or a rung with no account to transfer into.
    advice = "advice"


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


class PhysicalAssetKind(str, Enum):
    vehicle = "vehicle"
    metal = "metal"


class VehicleType(str, Enum):
    car = "car"
    motorcycle = "motorcycle"
    other = "other"


class PreciousMetal(str, Enum):
    gold = "gold"
    silver = "silver"
    platinum = "platinum"


class MetalMovementType(str, Enum):
    buy = "buy"
    sell = "sell"


class MetalForm(str, Enum):
    bullion = "bullion"
    coin = "coin"
    # Valued at melt value like the rest — see services/physical_assets.py.
    jewelry = "jewelry"


class WorkType(str, Enum):
    employee = "employee"
    # P.IVA in regime forfettario — the only one with a dedicated section.
    flat_rate = "flat_rate"
    ordinary = "ordinary"


class TaxComponent(str, Enum):
    substitute_tax = "substitute_tax"  # imposta sostitutiva
    inps = "inps"


class TaxPaymentKind(str, Enum):
    balance = "balance"  # saldo
    first_advance = "first_advance"  # 1° acconto (30 giugno)
    second_advance = "second_advance"  # 2° acconto (30 novembre)


class InvoiceStatus(str, Enum):
    collected = "collected"
    outstanding = "outstanding"


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
    hide_amounts: bool | None = None
    # Clearable like the anagrafica: `null` switches the section off.
    work_type: WorkType | None = None


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
    hide_amounts: bool
    work_type: WorkType | None = None
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
    # A date closes the account, an explicit null reopens it.
    closed_at: date_ | None = None


class Account(ORMBase):
    id: UUID
    name: str
    type: AccountType
    currency: str
    created_at: datetime
    closed_at: date_ | None = None
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


class TransferCreate(BaseModel):
    """
    A giroconto between two of the user's own accounts. Written as two
    linked legs, so the amount is a positive magnitude — the sign of each
    leg follows from which side it's on.
    """
    from_account_id: UUID
    to_account_id: UUID
    # A `transfer`-type category, or none — never "Varie".
    category_id: UUID | None = None
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    date: date_
    description: str | None = Field(default=None, max_length=500)


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
    # The other leg of a giroconto, when there is one. Null on every
    # opening balance and portfolio cash leg — read it as "may have".
    counterpart_transaction_id: UUID | None = None
    counterpart_account_id: UUID | None = None
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
    # Show a linked giroconto once, as its outgoing leg. Ignored when
    # filtering by account: there the leg on that account is the one to show.
    merge_transfer_legs: bool = False


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
    # Lets the client tie a status row back to the budget it came from —
    # previously it could only join on category_id, which was ambiguous
    # while two budgets could share one.
    budget_id: UUID
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
    # Filed on the cash-side `transfer` row; a transfer-type category or none.
    # Edited afterwards from that row, so the update schema doesn't carry it.
    category_id: UUID | None = None


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


# ---------------------------------------------------------------------------
# Physical assets — vehicles and precious metals
# ---------------------------------------------------------------------------

class PhysicalAssetCreate(BaseModel):
    """
    One schema for both kinds; the router rejects fields that belong to the
    other kind (422) rather than silently dropping them, so a client bug
    can't store a "car" with a purity.
    """

    kind: PhysicalAssetKind
    name: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=500)
    currency: str = Field(min_length=3, max_length=3)
    purchase_date: date_
    # For a metal these three describe its first buy movement.
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    # Optional: pay for it from this account (a negative `transfer` row).
    account_id: UUID | None = None
    category_id: UUID | None = None

    vehicle_type: VehicleType | None = None
    depreciation_rate: Decimal | None = Field(default=None, ge=0, lt=1, decimal_places=4)

    metal: PreciousMetal | None = None
    metal_form: MetalForm | None = None
    weight_grams: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    purity: Decimal | None = Field(default=None, gt=0, le=1, decimal_places=4)


class PhysicalAssetUpdate(BaseModel):
    # `kind`, `metal` and `currency` are immutable: changing any of them
    # turns the row into a different object, and would desync the frozen
    # base-currency amounts and the cash legs. A metal's weight, price and
    # dates are per movement, so purchase_* is vehicle-only here.
    name: str | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=500)
    purchase_date: date_ | None = None
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    vehicle_type: VehicleType | None = None
    depreciation_rate: Decimal | None = Field(default=None, ge=0, lt=1, decimal_places=4)
    metal_form: MetalForm | None = None
    purity: Decimal | None = Field(default=None, gt=0, le=1, decimal_places=4)


class PhysicalAssetSell(BaseModel):
    sold_at: date_
    sale_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    # Optional: the proceeds land on this account (a positive `transfer` row).
    account_id: UUID | None = None
    category_id: UUID | None = None


class MetalMovementCreate(BaseModel):
    type: MetalMovementType
    date: date_
    weight_grams: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    # Total for the movement. Required on a sale; optional on a buy (a gift).
    price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    account_id: UUID | None = None
    category_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=500)


class MetalMovement(BaseModel):
    id: UUID
    type: MetalMovementType
    date: date_
    weight_grams: Decimal
    price: Decimal | None
    price_base_currency: Decimal | None
    account_id: UUID | None
    notes: str | None


class PhysicalAssetValuationCreate(BaseModel):
    date: date_
    value: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)


class PhysicalAssetValuation(ORMBase):
    id: UUID
    date: date_
    value: Decimal
    notes: str | None = None


class PhysicalAssetWithValue(BaseModel):
    id: UUID
    kind: PhysicalAssetKind
    name: str
    notes: str | None
    currency: str
    purchase_date: date_
    purchase_price: Decimal | None
    purchase_price_base_currency: Decimal | None
    purchase_account_id: UUID | None
    sold_at: date_ | None
    sale_price: Decimal | None
    sale_price_base_currency: Decimal | None
    sale_account_id: UUID | None

    vehicle_type: VehicleType | None
    depreciation_rate: Decimal | None
    valuations: list[PhysicalAssetValuation]

    metal: PreciousMetal | None
    metal_form: MetalForm | None
    # A metal is a position: weight is what's held today, and the purchase
    # fields describe it — first buy date, average cost of the grams held
    # (None if any of them has no known cost). `sold_at` is the last sale
    # once nothing is left.
    weight_grams: Decimal | None
    purity: Decimal | None
    movements: list[MetalMovement]
    fine_weight_grams: Decimal | None  # weight_grams * purity
    spot_price_per_gram_base_currency: Decimal | None

    # None when it can't be priced (a metal whose spot quote is unavailable
    # today) — never 0, which would read as "worthless". Also None once sold.
    current_value_base_currency: Decimal | None
    value_date: date_
    # current (or sale) value minus purchase cost; None without a cost. For a
    # metal: unrealized, on the grams still held.
    pnl_base_currency: Decimal | None
    # Metal only: cumulative gain on grams already sold, at average cost.
    realized_pnl_base_currency: Decimal | None
    created_at: datetime


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
    # Vehicles and precious metals: part of net worth, never of cash — an
    # illiquid car doesn't extend the survival budget's runway.
    total_physical_assets_value: Decimal
    # Taxes accrued on collected flat-rate income, net of what's been paid —
    # subtracted from net worth. Negative = a credit (advances paid ahead of
    # the income they prepay).
    total_tax_liability: Decimal
    accounts: list[AccountBalance]
    holdings: list[HoldingWithValue]
    physical_assets: list[PhysicalAssetWithValue]


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
    total_physical_assets_value_base_currency: Decimal
    total_liabilities_base_currency: Decimal
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
    # Excludes the accounts holding the P.IVA tax provision.
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


# ---------------------------------------------------------------------------
# Savings goals and the waterfall
# ---------------------------------------------------------------------------

class SavingsGoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: SavingsGoalKind
    priority: int = Field(ge=0)
    target_mode: TargetMode
    target_months: Decimal | None = Field(default=None, gt=0, max_digits=5, decimal_places=2)
    target_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)


class SavingsGoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    priority: int | None = Field(default=None, ge=0)
    target_mode: TargetMode | None = None
    target_months: Decimal | None = Field(default=None, gt=0, max_digits=5, decimal_places=2)
    target_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)


class SavingsGoalSource(ORMBase):
    id: UUID
    account_id: UUID


class SavingsGoalSourceCreate(BaseModel):
    account_id: UUID


class SavingsGoal(ORMBase):
    id: UUID
    name: str
    kind: SavingsGoalKind
    priority: int
    target_mode: TargetMode
    target_months: Decimal | None = None
    target_amount: Decimal | None = None
    sources: list[SavingsGoalSource] = Field(default_factory=list)
    deleted_at: datetime | None = None


class WaterfallStep(BaseModel):
    goal_id: UUID
    name: str
    kind: SavingsGoalKind
    priority: int
    target_mode: TargetMode
    # None when the target can't be computed yet — a dynamic target needs
    # at least one complete month of history. Such a rung is skipped, never
    # treated as already funded, which would hand its quota to the next one
    # down the ladder.
    target_amount: Decimal | None = None
    target_unavailable: bool = False
    current_amount: Decimal
    gap: Decimal
    allocated_amount: Decimal
    funding_percentage: float
    is_funded: bool


class WaterfallAction(BaseModel):
    kind: WaterfallActionKind
    goal_id: UUID
    goal_name: str
    amount: Decimal
    currency: str
    from_account_id: UUID | None = None
    from_account_name: str | None = None
    to_account_id: UUID | None = None
    to_account_name: str | None = None
    reason: str


class WaterfallPlan(BaseModel):
    base_currency: str
    period_start: date_
    period_end: date_
    income_total: Decimal
    savings_quota: Decimal
    already_allocated: Decimal
    steps: list[WaterfallStep]
    unallocated_amount: Decimal
    actions: list[WaterfallAction]


class WaterfallExecutionItem(BaseModel):
    goal_id: UUID
    from_account_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class WaterfallExecuteRequest(BaseModel):
    """
    The client sends back the actions it displayed, with explicit amounts.

    Deliberately not opaque action ids: those would need an ephemeral
    server-side store with a TTL, and the CSV import already has one of
    those documented as the thing blocking a second backend replica. Every
    field is re-validated server-side, so echoing them back is safe.
    """

    date: date_ | None = None
    items: list[WaterfallExecutionItem] = Field(min_length=1)


class SavingsAllocation(ORMBase):
    id: UUID
    goal_id: UUID
    transaction_id: UUID
    period_start: date_
    amount_base_currency: Decimal
    created_at: datetime


class WaterfallExecuteResponse(BaseModel):
    allocations: list[SavingsAllocation]
    transactions: list["Transaction"]


# ---------------------------------------------------------------------------
# P.IVA forfettaria — invoices, F24 payments, provision. Amounts in EUR.
# ---------------------------------------------------------------------------

class FlatRateSettings(ORMBase):
    activity_start_date: date_ | None
    safety_margin: Decimal


class FlatRateSettingsUpdate(BaseModel):
    # Both clearable/settable independently; omitted = unchanged.
    activity_start_date: date_ | None = None
    safety_margin: Decimal | None = Field(default=None, ge=0, le=1, max_digits=5, decimal_places=4)


class FlatRateYear(BaseModel):
    year: int
    profitability_coefficient: Decimal
    # Resolved: the override if set, else 5% within the first five years of
    # activity and 15% after.
    substitute_tax_rate: Decimal
    substitute_tax_rate_is_automatic: bool
    # Last year of the 5% start-up rate; None without a start date.
    startup_last_year: int | None
    inps_rate: Decimal
    rivalsa_rate: Decimal
    # The user's explicit choice; None = follow the suggestion.
    provision_rate: Decimal | None
    # coefficient × (tax + INPS): what one euro collected owes for its year.
    load_rate: Decimal
    # coefficient × (tax + 80% INPS): the advances it triggers for next year.
    advance_rate: Decimal
    # Share of each euro collected this year the F24s will need, before margin.
    needed_rate: Decimal
    suggested_provision_rate: Decimal
    effective_provision_rate: Decimal


class FlatRateYearUpdate(BaseModel):
    profitability_coefficient: Decimal | None = Field(
        default=None, gt=0, le=1, max_digits=5, decimal_places=4
    )
    # Send null to go back to automatic (5% for the first five years).
    substitute_tax_rate: Decimal | None = Field(
        default=None, ge=0, lt=1, max_digits=5, decimal_places=4
    )
    inps_rate: Decimal | None = Field(default=None, ge=0, lt=1, max_digits=5, decimal_places=4)
    rivalsa_rate: Decimal | None = Field(default=None, ge=0, lt=1, max_digits=5, decimal_places=4)
    # Send null to go back to the suggested rate.
    provision_rate: Decimal | None = Field(default=None, ge=0, le=1, max_digits=5, decimal_places=4)


class InvoiceCreate(BaseModel):
    number: str | None = Field(default=None, max_length=50)
    client: str = Field(min_length=1, max_length=200)
    issue_date: date_
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    # None = the issue year's default (4% with rivalsa, 0 without).
    rivalsa_rate: Decimal | None = Field(default=None, ge=0, lt=1, max_digits=5, decimal_places=4)
    # None = automatic: charged when fee + rivalsa exceeds €77.47.
    stamp_duty: bool | None = None
    provision_rate: Decimal | None = Field(default=None, ge=0, le=1, max_digits=5, decimal_places=4)
    notes: str | None = Field(default=None, max_length=500)


class InvoiceUpdate(BaseModel):
    number: str | None = Field(default=None, max_length=50)
    client: str | None = Field(default=None, min_length=1, max_length=200)
    issue_date: date_ | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    rivalsa_rate: Decimal | None = Field(default=None, ge=0, lt=1, max_digits=5, decimal_places=4)
    stamp_duty: bool | None = None
    # Clearable (null = back to the year's rate), like number and notes.
    provision_rate: Decimal | None = Field(default=None, ge=0, le=1, max_digits=5, decimal_places=4)
    notes: str | None = Field(default=None, max_length=500)
    # Re-dates a collection (and the income written by it). Not clearable
    # here: undoing a collection is /uncollect, which also retires that income.
    collected_on: date_ | None = None


class InvoiceCollect(BaseModel):
    """
    Mark an invoice collected. At most one of: link an existing income
    movement (`transaction_id`, typically imported from CSV), or write a new
    one on an account (`account_id`, optional income `category_id`). Neither
    just records the date.
    """

    collected_on: date_
    transaction_id: UUID | None = None
    account_id: UUID | None = None
    category_id: UUID | None = None


class Invoice(BaseModel):
    id: UUID
    number: str | None
    client: str
    issue_date: date_
    collected_on: date_ | None
    amount: Decimal
    rivalsa_rate: Decimal
    rivalsa_amount: Decimal
    stamp_duty: bool
    stamp_duty_amount: Decimal
    total: Decimal
    # The collection year once collected, the issue year until then.
    fiscal_year: int
    provision_rate: Decimal | None
    applied_provision_rate: Decimal
    # Per-invoice estimate, gross of the INPS deduction (so on the safe
    # side); the year's figures apply the deduction.
    taxable_base: Decimal
    substitute_tax: Decimal
    inps: Decimal
    substitute_tax_advance: Decimal
    inps_advance: Decimal
    to_provision: Decimal
    transaction_id: UUID | None
    owns_transaction: bool
    transaction_account_id: UUID | None
    transaction_deleted: bool
    notes: str | None
    created_at: datetime


class TaxPaymentCreate(BaseModel):
    paid_on: date_
    fiscal_year: int = Field(ge=2000, le=2100)
    component: TaxComponent
    kind: TaxPaymentKind
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)
    # Optional: paid from this account (a negative one-sided `transfer`).
    account_id: UUID | None = None
    category_id: UUID | None = None


class TaxPaymentUpdate(BaseModel):
    paid_on: date_ | None = None
    fiscal_year: int | None = Field(default=None, ge=2000, le=2100)
    component: TaxComponent | None = None
    kind: TaxPaymentKind | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)


class TaxPayment(BaseModel):
    id: UUID
    paid_on: date_
    fiscal_year: int
    component: TaxComponent
    kind: TaxPaymentKind
    amount: Decimal
    notes: str | None
    transaction_id: UUID | None
    account_id: UUID | None
    created_at: datetime


class ProvisionSourceCreate(BaseModel):
    account_id: UUID
    # None = the account's cash; set = that holding inside the account.
    asset_id: UUID | None = None


class ProvisionSource(BaseModel):
    id: UUID
    account_id: UUID
    account_name: str
    account_currency: str
    asset: Asset | None
    quantity: Decimal | None
    price: Decimal | None
    # None when it can't be priced right now — never 0.
    value_base_currency: Decimal | None
    # Whole units of `asset` the same account's cash could buy at `price`,
    # for products bought in whole shares only (e.g. a money-market ETF).
    buyable_units: int | None


class ProvisionStatus(BaseModel):
    total_base_currency: Decimal
    sources: list[ProvisionSource]


class F24Deadline(BaseModel):
    due_date: date_
    fiscal_year: int
    component: TaxComponent
    kind: TaxPaymentKind
    amount_due: Decimal
    amount_paid: Decimal
    # True while the year it's computed on hasn't closed yet.
    is_estimate: bool


class FlatRateYearFigures(BaseModel):
    revenue: Decimal  # collected in the year: fee + rivalsa + bollo
    revenue_limit: Decimal
    taxable_base: Decimal  # revenue × coefficient
    inps: Decimal
    # INPS contributions paid during the year, deducted from the tax base.
    inps_deducted: Decimal
    substitute_tax: Decimal
    liability: Decimal  # substitute_tax + inps
    advances_due: Decimal  # this year's advances, computed on the previous one
    paid: Decimal  # F24 payments for this fiscal year
    to_provision: Decimal  # Σ per collected invoice: total × its rate
    outstanding: Decimal  # issued this year, not collected yet
    invoice_count: int


class FlatRateSummary(BaseModel):
    year: int
    as_of: date_
    params: FlatRateYear
    figures: FlatRateYearFigures
    # As of today, across every year: accrued taxes net of payments (the
    # net-worth liability; negative = credit) and everything the F24s will
    # still ask for income collected so far, next year's advances included.
    tax_liability: Decimal
    cash_requirement: Decimal
    provision: ProvisionStatus
    gap: Decimal  # provision − cash_requirement
    deadlines: list[F24Deadline]
