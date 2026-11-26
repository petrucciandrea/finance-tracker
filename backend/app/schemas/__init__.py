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
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

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
    stamp_duty = "stamp_duty"  # imposta di bollo sulle fatture elettroniche


class TaxPaymentKind(str, Enum):
    balance = "balance"  # saldo
    first_advance = "first_advance"  # 1° acconto (30 giugno)
    second_advance = "second_advance"  # 2° acconto (30 novembre)
    # The bollo's quarters (codici tributo 2521–2524).
    q1 = "q1"
    q2 = "q2"
    q3 = "q3"
    q4 = "q4"


_QUARTER_KINDS = {"q1", "q2", "q3", "q4"}


def check_component_kind(component: "TaxComponent | None", kind: "TaxPaymentKind | None") -> None:
    if component is None or kind is None:
        return
    if (component == TaxComponent.stamp_duty) != (kind.value in _QUARTER_KINDS):
        raise ValueError("The bollo is paid per quarter (q1–q4), the taxes per saldo/acconto")


class TaxPaymentStatus(str, Enum):
    # Authorised (a direct debit on the AdE portal, an F24 booked at the
    # bank) but not taken yet: moves nothing until confirmed.
    scheduled = "scheduled"
    paid = "paid"


class VehicleDeadlineKind(str, Enum):
    insurance = "insurance"  # assicurazione RC
    road_tax = "road_tax"  # bollo auto
    inspection = "inspection"  # revisione
    service = "service"  # tagliando
    other = "other"


class AlertTone(str, Enum):
    danger = "danger"
    warn = "warn"


class AlertRepeat(str, Enum):
    # Shown on every visit until the cause goes away; dismissing it only
    # hides it until the app is opened again.
    every_visit = "every_visit"
    # Dismissed for good, until its `id` changes (the cause changed).
    once = "once"


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

# Emails are case-insensitive in practice, but the unique index is not: without
# normalising, Foo@x.com and foo@x.com would be two accounts.
LowerEmail = Annotated[EmailStr, AfterValidator(str.lower)]

# bcrypt only reads 72 bytes, so the cap is not about hashing: it keeps a
# multi-megabyte "password" from being parsed and held in memory.
_PASSWORD_MAX = 256


class UserCreate(BaseModel):
    email: LowerEmail
    password: str = Field(min_length=8, max_length=_PASSWORD_MAX)
    base_currency: str = Field(min_length=3, max_length=3, description="ISO 4217 code, e.g. EUR")
    # Literal[True]: unticked is a 422, so consent can't be skipped by calling
    # the API directly instead of the form.
    accept_terms: Literal[True]


class UserLogin(BaseModel):
    email: LowerEmail
    password: str = Field(max_length=_PASSWORD_MAX)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserUpdate(BaseModel):
    email: LowerEmail | None = None
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


class AccountDeleteRequest(BaseModel):
    password: str = Field(max_length=_PASSWORD_MAX)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(max_length=_PASSWORD_MAX)
    new_password: str = Field(min_length=8, max_length=_PASSWORD_MAX)


class User(ORMBase):
    id: UUID
    email: EmailStr
    base_currency: str
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date_ | None = None
    hide_amounts: bool
    work_type: WorkType | None = None
    approval_status: Literal["pending", "approved", "rejected"]
    email_verified_at: datetime | None = None
    created_at: datetime


class PublicConfig(BaseModel):
    """What the login/register pages need to know to show only what works."""

    registration_mode: Literal["closed", "approval", "open"]
    email_enabled: bool


class EmailRequest(BaseModel):
    email: LowerEmail


class TokenRequest(BaseModel):
    token: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=_PASSWORD_MAX)


class ApprovalTokenRequest(BaseModel):
    token: str


class ApprovalDecisionRequest(BaseModel):
    token: str
    decision: Literal["approve", "reject"]


class ApprovalRequestInfo(BaseModel):
    email: EmailStr
    approval_status: Literal["pending", "approved", "rejected"]
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
    # Expense only: the part paid on behalf of others (same currency as the
    # expense). The spend counts only the rest.
    lent_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=8)
    # Income only: the expense this pays back.
    repays_transaction_id: UUID | None = None


class CreditOffsetCreate(BaseModel):
    """
    Settle (part of) a credit in kind: the friend paid for something of the
    user's instead of handing cash back. Written as the user's own spend plus
    the repayment closing the credit, on one account, so cash doesn't move.
    `amount` is a positive magnitude, in the account's (= the expense's) currency.
    """
    credit_transaction_id: UUID
    account_id: UUID
    # An expense category for the user's own share; none falls back to "Varie".
    category_id: UUID | None = None
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    date: date_
    description: str | None = Field(default=None, max_length=500)
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
    # Explicit null clears it, which is why these are read from the unset fields.
    lent_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=8)
    repays_transaction_id: UUID | None = None


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
    # Expense: the share paid for others, and how much of it has come back.
    # `repaid_amount` is null whenever `lent_amount` is.
    lent_amount: Decimal | None = None
    repaid_amount: Decimal | None = None
    # Income that pays back an expense; it is not income in any total.
    repays_transaction_id: UUID | None = None
    # The other leg of a credit settled in kind (spend ↔ repayment).
    offset_transaction_id: UUID | None = None
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
    row_numbers: list[int] = Field(
        max_length=5000, description="Rows to actually commit, e.g. excluding duplicates"
    )


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


class ExposureDimension(str, Enum):
    asset_class = "asset_class"
    region = "region"
    sector = "sector"
    currency = "currency"


# Fixed lists, never free text: two spellings of one region would split it in
# two. `cash` is an asset class the allocation computes (uninvested cash on
# investment accounts), never one a product is given.
EXPOSURE_BUCKETS: dict[str, tuple[str, ...]] = {
    "asset_class": (
        "equity", "bond", "money_market", "commodity", "crypto", "real_estate", "other",
    ),
    "region": (
        "north_america", "europe_ex_italy", "italy", "united_kingdom", "japan",
        "pacific_ex_japan", "emerging", "not_applicable",
    ),
    # GICS.
    "sector": (
        "information_technology", "financials", "health_care", "consumer_discretionary",
        "communication_services", "industrials", "consumer_staples", "energy", "materials",
        "utilities", "real_estate",
    ),
    "currency": ("EUR", "USD", "GBP", "JPY", "CHF", "other"),
}


class ExposureSource(str, Enum):
    user = "user"  # the user's own weights
    reference = "reference"  # app/data/asset_exposures.json
    default = "default"  # what the type implies (a stock is equity, crypto is crypto)


class ExposureWeight(BaseModel):
    bucket: str = Field(min_length=1, max_length=30)
    weight: Decimal = Field(gt=0, le=100, max_digits=7, decimal_places=4)


class AssetExposureDimension(BaseModel):
    dimension: ExposureDimension
    # None = nothing known: the whole product is unclassified here.
    source: ExposureSource | None = None
    weights: list[ExposureWeight]
    as_of: date_ | None = None
    notes: str | None = None
    source_urls: list[str] = Field(default_factory=list)


class AssetExposures(BaseModel):
    asset: "Asset"
    dimensions: list[AssetExposureDimension]


class AssetExposureUpdate(BaseModel):
    weights: list[ExposureWeight] = Field(max_length=20)
    as_of: date_ | None = None
    notes: str | None = Field(default=None, max_length=500)


class ExposureSuggestion(BaseModel):
    """Yahoo's profile of a single stock, mapped to our buckets. Nothing is saved."""

    asset_id: UUID
    raw_sector: str | None = None
    raw_country: str | None = None
    weights: dict[ExposureDimension, list[ExposureWeight]]


class AllocationBucketValue(BaseModel):
    bucket: str
    value: Decimal
    percentage: float


class AllocationPositionKind(str, Enum):
    holding = "holding"
    metal = "metal"
    cash = "cash"


class AllocationPosition(BaseModel):
    kind: AllocationPositionKind
    label: str
    asset: "Asset | None" = None
    account_name: str | None = None
    # None = no stored price or rate: left out of every total.
    value: Decimal | None = None
    source: ExposureSource | None = None
    as_of: date_ | None = None
    # The weights used for this dimension (empty = unclassified).
    weights: list[ExposureWeight]


class PortfolioAllocation(BaseModel):
    """
    Pillar 4 only: holdings funding an emergency fund or a dated goal, and
    the tax provision, are out (`excluded_value`) — counted, they would make
    the portfolio look prudent with money that is due within a few years.
    """

    dimension: ExposureDimension
    base_currency: str
    # What the percentages are of: everything valued in this dimension (for
    # `sector`, only the equity part of it).
    total: Decimal
    classified_value: Decimal
    # classified / total, 0-100. Below 90 the rules don't judge.
    coverage: float
    buckets: list[AllocationBucketValue]
    unclassified_value: Decimal
    excluded_value: Decimal
    # Value the dimension doesn't apply to, left out of `total`: the
    # non-equity part for `sector`, `not_applicable` (gold, crypto, money
    # market) for `region`.
    outside_value: Decimal = Decimal("0")
    has_unpriced: bool
    # Positions whose weights are dated more than a year ago.
    stale_count: int
    positions: list[AllocationPosition]


class PortfolioRuleKind(str, Enum):
    target = "target"
    max_share = "max_share"
    excess_cash = "excess_cash"
    min_invested = "min_invested"


class PortfolioRuleCreate(BaseModel):
    """Each kind takes its own fields; the router 422s the wrong ones."""

    kind: PortfolioRuleKind
    # target: asset_class | region. max_share: any dimension, or `position`
    # with the asset id as bucket.
    dimension: str | None = Field(default=None, max_length=12)
    bucket: str | None = Field(default=None, max_length=40)
    target_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    tolerance_pct: Decimal | None = Field(
        default=None, gt=0, le=50, max_digits=5, decimal_places=2
    )
    max_pct: Decimal | None = Field(default=None, gt=0, le=100, max_digits=5, decimal_places=2)
    min_pct: Decimal | None = Field(default=None, gt=0, le=100, max_digits=5, decimal_places=2)
    threshold_amount: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=2
    )
    threshold_months: Decimal | None = Field(
        default=None, gt=0, le=60, max_digits=4, decimal_places=1
    )


class PortfolioRule(ORMBase):
    id: UUID
    kind: PortfolioRuleKind
    dimension: str | None = None
    bucket: str | None = None
    target_pct: Decimal | None = None
    tolerance_pct: Decimal | None = None
    max_pct: Decimal | None = None
    min_pct: Decimal | None = None
    threshold_amount: Decimal | None = None
    threshold_months: Decimal | None = None


class RuleState(str, Enum):
    ok = "ok"
    over = "over"
    under = "under"
    # Not judged: too little of the dimension is classified, no history to
    # size the idle-cash threshold, or nothing invested yet.
    unknown = "unknown"


class PortfolioRuleStatus(BaseModel):
    rule: PortfolioRule
    state: RuleState
    actual_pct: float | None = None
    actual_amount: Decimal | None = None
    # excess_cash: the threshold in money (months × average spend).
    limit_amount: Decimal | None = None
    # unknown only: coverage | no_history | nothing_invested
    reason: str | None = None
    # max_share on a position: the product's symbol, for display.
    label: str | None = None


class ContributionSplit(BaseModel):
    bucket: str
    amount: Decimal


class PortfolioRulesStatus(BaseModel):
    base_currency: str
    rules: list[PortfolioRuleStatus]
    # Cash nothing needs: operating accounts above pillar 1's target, minus the
    # emergency fund's gap and the scheduled debits, plus idle broker cash.
    # None while pillar 1's target is unknown.
    idle_cash: Decimal | None = None
    invested: Decimal
    # invested / (invested + idle_cash), 0-100.
    invested_share: float | None = None
    # This month's quota for the open-ended long-term rung, and how to split
    # it across the asset-class targets to close the gaps without selling.
    contribution: Decimal
    contribution_split: list[ContributionSplit]


class PresetTarget(BaseModel):
    dimension: ExposureDimension
    bucket: str
    target_pct: Decimal


class PortfolioPreset(BaseModel):
    key: str
    label: str
    description: str
    targets: list[PresetTarget]


class ApplyPresetRequest(BaseModel):
    preset: str = Field(max_length=30)
    tolerance_pct: Decimal = Field(
        default=Decimal("5"), gt=0, le=50, max_digits=5, decimal_places=2
    )


class TargetWeight(BaseModel):
    bucket: str = Field(min_length=1, max_length=40)
    target_pct: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class TargetsReplace(BaseModel):
    """
    Every target of one dimension at once, as the slider editor sends them:
    one-by-one creation can't move from one mix to another, since the sum
    would cross 100 halfway. A bucket at 0 is not stored (no target, so it
    isn't judged); an empty list removes the dimension's targets.
    """

    dimension: ExposureDimension
    tolerance_pct: Decimal = Field(
        default=Decimal("5"), gt=0, le=50, max_digits=5, decimal_places=2
    )
    targets: list[TargetWeight] = Field(max_length=20)


class AssetSearchResult(BaseModel):
    symbol: str
    name: str
    asset_type: AssetType


class AssetTransactionType(str, Enum):
    buy = "buy"
    sell = "sell"


class AssetTransactionCreate(BaseModel):
    account_id: UUID
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9.\-=^]*$")
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
    row_numbers: list[int] = Field(
        max_length=5000, description="Rows to actually commit, e.g. excluding duplicates"
    )


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


class VehicleDeadlineCreate(BaseModel):
    physical_asset_id: UUID
    kind: VehicleDeadlineKind
    label: str | None = Field(default=None, min_length=1, max_length=100)
    due_date: date_
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    # Paid from this account: the amount becomes a commitment on it.
    account_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=500)


class VehicleDeadlineUpdate(BaseModel):
    kind: VehicleDeadlineKind | None = None
    label: str | None = Field(default=None, min_length=1, max_length=100)
    due_date: date_ | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    account_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=500)


class VehicleDeadlineComplete(BaseModel):
    done_on: date_
    # Set = create the next occurrence (same kind, label, amount, account).
    next_due_date: date_ | None = None


class VehicleDeadline(ORMBase):
    id: UUID
    physical_asset_id: UUID
    kind: VehicleDeadlineKind
    label: str | None
    due_date: date_
    amount: Decimal | None
    currency: str
    account_id: UUID | None
    notes: str | None
    done_on: date_ | None
    created_at: datetime


class CommitmentItem(BaseModel):
    label: str
    due_date: date_
    amount: Decimal


class AccountCommitment(BaseModel):
    """What's due to leave an account (scheduled F24s, vehicle deadlines
    paid from it) against what's in it."""

    account_id: UUID
    account_name: str
    currency: str
    balance: Decimal
    committed: Decimal
    # The larger of 15 (in the account's currency) and 20% of `committed`.
    margin: Decimal
    # balance below this = "close to it"; below `committed` = not enough.
    threshold: Decimal
    # The date of the account's latest movement: a balance is only as fresh
    # as the last statement imported.
    last_movement_on: date_ | None
    items: list[CommitmentItem]


class Alert(BaseModel):
    """
    One thing that needs attention. Structured rather than a sentence: the
    client words it and formats the amounts, so "Nascondi importi" masks
    them like everywhere else.

    kinds: account_short (balance below what's due from it), account_near
    (above it by less than the margin), f24_overdue / f24_upcoming (lines
    neither paid nor scheduled), scheduled_unconfirmed (its date passed and
    the debit wasn't confirmed), vehicle_overdue / vehicle_upcoming;
    the plan's (services/plan_alerts.py): goal_overdue, goal_due_soon,
    goal_behind_schedule, goal_horizon_mismatch, allocation_out_of_band,
    allocation_over_cap, excess_cash, below_min_invested_share,
    investing_without_emergency_fund, exposure_data_stale.
    """

    # Stable while its cause is unchanged, so a dismissal can be remembered.
    id: str
    kind: str
    tone: AlertTone
    repeat: AlertRepeat
    # What it is about: "bollo fatture — 3° trimestre 2026", "Panda · assicurazione".
    label: str
    due_date: date_ | None = None
    amount: Decimal | None = None
    currency: str | None = None
    account_id: UUID | None = None
    account_name: str | None = None
    # account_* only.
    balance: Decimal | None = None
    committed: Decimal | None = None
    margin: Decimal | None = None
    # Plan and portfolio alerts: the share measured and the limit set (both
    # percentages, 0-100), and what they are about.
    percentage: float | None = None
    limit_percentage: float | None = None
    dimension: str | None = None
    bucket: str | None = None
    # A page in the app to go and fix it.
    link: str | None = None


class AlertsResponse(BaseModel):
    alerts: list[Alert]
    commitments: list[AccountCommitment]


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
    # The same, split: what's owed and what was prepaid (both ≥ 0, their
    # difference is total_tax_liability). The year in progress stays gross —
    # its accrued taxes are debt, its advances credit — until it closes.
    total_tax_debt: Decimal
    total_tax_credit: Decimal
    # Money fronted for others and not yet paid back: part of net worth, never
    # of cash (it can't be spent until it comes back).
    total_credits_value: Decimal
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
    total_credits_base_currency: Decimal
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
    operating_cash_months: Decimal
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
    operating_cash_months: Decimal | None = Field(
        default=None, ge=0, le=24, max_digits=4, decimal_places=1
    )
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
    # The base every bucket is computed on: gross income minus the imposta
    # + INPS on the P.IVA invoices collected in the period.
    income_total: Decimal
    gross_income_total: Decimal
    flat_rate_tax_total: Decimal
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
    # Net of flat-rate taxes, as the allocation model's base.
    monthly_income: Decimal | None = None
    # What the runway lives off: operating_cash + emergency_fund + goal_excess
    # − committed_outflows. Not every account: the tax provision is the
    # State's, a dated goal's cash has a job, and broker cash is pillar 4's.
    total_cash_balance: Decimal
    # Pillar 1: the accounts no goal or provision claims, investment ones aside.
    operating_cash: Decimal = Decimal("0")
    # Pillar 2, valued like the cascade (holdings from the caches only).
    emergency_fund: Decimal = Decimal("0")
    # Cash on goal accounts above every goal's target: nobody needs it.
    goal_excess: Decimal = Decimal("0")
    # Debits already scheduled from the operating accounts (F24, vehicles).
    committed_outflows: Decimal = Decimal("0")
    # An emergency-fund holding with no cached price counted as nothing.
    has_unpriced_holdings: bool = False
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
    # Omitted = placed by the server: a dated goal among the dated ones by
    # its date, anything else at the bottom (above an open-ended rung).
    priority: int | None = Field(default=None, ge=0)
    target_mode: TargetMode
    target_months: Decimal | None = Field(default=None, gt=0, max_digits=5, decimal_places=2)
    target_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    # medium_term + fixed_amount only (422 otherwise).
    target_date: date_ | None = None


class SavingsGoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    priority: int | None = Field(default=None, ge=0)
    target_mode: TargetMode | None = None
    target_months: Decimal | None = Field(default=None, gt=0, max_digits=5, decimal_places=2)
    target_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    target_date: date_ | None = None
    # Set = reached and spent: the goal leaves the cascade and its sources are
    # retired. Cleared = back in the cascade, with no sources.
    completed_at: date_ | None = None


class SavingsGoalSource(ORMBase):
    id: UUID
    account_id: UUID
    # Set = that holding inside the account, valued from the caches.
    asset_id: UUID | None = None
    asset: Asset | None = None


class SavingsGoalSourceCreate(BaseModel):
    account_id: UUID
    asset_id: UUID | None = None


class SavingsGoal(ORMBase):
    id: UUID
    name: str
    kind: SavingsGoalKind
    priority: int
    target_mode: TargetMode
    target_months: Decimal | None = None
    target_amount: Decimal | None = None
    target_date: date_ | None = None
    completed_at: date_ | None = None
    sources: list[SavingsGoalSource] = Field(default_factory=list)
    deleted_at: datetime | None = None

    @field_validator("sources", mode="before")
    @classmethod
    def _active_sources_only(cls, value: object) -> object:
        # The ORM relationship loads detached (soft-deleted) mappings too;
        # listed here they would show an account as still linked after it was
        # detached, or freed by completing the goal.
        if isinstance(value, list):
            return [s for s in value if getattr(s, "deleted_at", None) is None]
        return value


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
    # A holding source with no cached price or rate: `current_amount` leaves
    # it out, so the goal reads as less funded than it may be.
    has_unpriced_sources: bool = False
    # Dated goals only (None otherwise).
    target_date: date_ | None = None
    # Monthly contributions left, this month included (0 once the date passed).
    months_left: int | None = None
    # What this month puts aside: executed giroconti + the pending suggestion,
    # one-off surplus included.
    this_month_amount: Decimal | None = None
    # What's left after this month, over the months after it: the rate needed
    # from next month on.
    required_monthly: Decimal | None = None
    # What the monthly quota alone gives the goal from next month (the one-off
    # surplus is a stock, so it is not projected forward).
    monthly_pace: Decimal | None = None
    # The month the gap closes at `monthly_pace`; None = never at this pace.
    projected_date: date_ | None = None
    on_track: bool | None = None


class WaterfallAction(BaseModel):
    kind: WaterfallActionKind
    # None for the tax provision rung (purpose = tax_provision).
    goal_id: UUID | None = None
    goal_name: str
    purpose: str = "goal"
    amount: Decimal
    currency: str
    from_account_id: UUID | None = None
    from_account_name: str | None = None
    to_account_id: UUID | None = None
    to_account_name: str | None = None
    reason: str


class TaxProvisionRung(BaseModel):
    """
    The P.IVA provision as the cascade's first rung: what the F24s will still
    ask (less what's already scheduled from other accounts) against what the
    provision holds. Before any goal: it is a debt, not a saving.
    """

    target: Decimal
    current: Decimal
    gap: Decimal
    allocated_amount: Decimal
    account_id: UUID | None = None
    account_name: str | None = None


class WaterfallPlan(BaseModel):
    base_currency: str
    period_start: date_
    period_end: date_
    income_total: Decimal  # net of flat-rate taxes, as in AllocationStatus
    gross_income_total: Decimal
    flat_rate_tax_total: Decimal
    savings_quota: Decimal
    already_allocated: Decimal
    steps: list[WaterfallStep]
    unallocated_amount: Decimal
    actions: list[WaterfallAction]
    # Pillar 1's surplus: what the operating accounts hold beyond their target
    # and the debits scheduled from them. None while the target is unknown.
    operating_surplus: Decimal | None = None
    # What the cascade distributed: the larger of the quota still to place and
    # the surplus (the quota's money already sits in that surplus, so the two
    # are not added).
    budget: Decimal = Decimal("0")
    tax_provision: TaxProvisionRung | None = None
    # Where the suggested giroconti leave from: the plan's account, or (no
    # account in the plan) the operating account with the most cash.
    source_account_id: UUID | None = None
    source_is_fallback: bool = False
    # What goal accounts hold beyond every goal they fund (shared accounts
    # are split in cascade order): free money, moved from those accounts.
    goal_account_excess: Decimal = Decimal("0")
    goal_account_excesses: list["AccountAmount"] = Field(default_factory=list)


class AccountAmount(BaseModel):
    account_id: UUID
    account_name: str
    amount: Decimal


class PillarKey(str, Enum):
    """
    The plan's four pillars, in the order money should fill them:
    1 operating cash (the month's spending), 2 emergency fund, 3 savings for
    dated or known expenses, 4 long-term investing. Pillars 2-4 hold the
    goals of the matching `SavingsGoalKind`; pillar 1 is computed.
    """

    operating = "operating"
    emergency = "emergency"
    planned = "planned"
    investing = "investing"


class PillarItemKind(str, Enum):
    # Pillar 3 lines that aren't goals: money already spoken for by the app's
    # other sections, shown beside the goals rather than turned into them.
    tax_provision = "tax_provision"
    vehicle_deadline = "vehicle_deadline"
    # Pillar 4: cash on investment accounts no goal claims.
    uninvested_cash = "uninvested_cash"
    # Pillar 4: holdings no goal or provision claims.
    free_holdings = "free_holdings"
    # Pillar 1: what a goal account holds beyond every goal it funds.
    goal_account_excess = "goal_account_excess"


class PillarItem(BaseModel):
    kind: PillarItemKind
    label: str
    # What it needs (a deadline's amount, the F24s' requirement) — None for
    # pillar 4's lines, which are only "what's there".
    amount: Decimal | None = None
    # What is set aside for it, when the app knows (the tax provision).
    available: Decimal | None = None
    currency: str
    due_date: date_ | None = None
    # amount / months to the due date: what to put aside each month for it.
    monthly: Decimal | None = None
    account_name: str | None = None


class Pillar(BaseModel):
    key: PillarKey
    # Sum of the known targets; None when none is known (pillar 1 without a
    # complete month of history, pillar 4 always — it has no ceiling).
    target: Decimal | None = None
    current: Decimal
    gap: Decimal | None = None
    # What to put aside each month to stay on schedule: the dated goals'
    # required rates plus the items' monthly shares. None = nothing dated.
    monthly_required: Decimal | None = None
    steps: list[WaterfallStep]
    items: list[PillarItem]


class PillarsResponse(BaseModel):
    base_currency: str
    period_start: date_
    operating_cash_months: Decimal
    # The average over the plan's lookback, complete months only; None = unknown.
    monthly_total_expenses: Decimal | None = None
    # Some holding has no cached price or rate: its pillar reads low.
    has_unpriced_holdings: bool
    pillars: list[Pillar]


class WaterfallExecutionItem(BaseModel):
    # A goal; without one, `to_account_id` is the tax provision's account.
    # With both, `to_account_id` is the account to link to a goal that has
    # none yet (executing the advice "no account linked").
    goal_id: UUID | None = None
    to_account_id: UUID | None = None
    from_account_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)

    @model_validator(mode="after")
    def _a_destination(self) -> "WaterfallExecutionItem":
        if self.goal_id is None and self.to_account_id is None:
            raise ValueError("Give goal_id, to_account_id or both")
        return self


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
    # Only in the activity's second year: from the day after the first
    # declaration (30 June) the suggestion drops to the steady rate. The two
    # rates above apply until then; an explicit provision_rate covers both.
    provision_switch_date: date_ | None
    suggested_provision_rate_after_switch: Decimal | None


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
    # When SdI delivered it, if not the issue date: the bollo's quarter follows it.
    sdi_delivered_on: date_ | None = None
    provision_rate: Decimal | None = Field(default=None, ge=0, le=1, max_digits=5, decimal_places=4)
    notes: str | None = Field(default=None, max_length=500)


class InvoiceUpdate(BaseModel):
    number: str | None = Field(default=None, max_length=50)
    client: str | None = Field(default=None, min_length=1, max_length=200)
    issue_date: date_ | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    rivalsa_rate: Decimal | None = Field(default=None, ge=0, lt=1, max_digits=5, decimal_places=4)
    stamp_duty: bool | None = None
    # Clearable: null = delivered on the issue date.
    sdi_delivered_on: date_ | None = None
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
    sdi_delivered_on: date_ | None
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
    # For a scheduled payment: the day the debit is expected.
    paid_on: date_
    fiscal_year: int = Field(ge=2000, le=2100)
    component: TaxComponent
    kind: TaxPaymentKind
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)
    status: TaxPaymentStatus = TaxPaymentStatus.paid
    # Required (422 without it; Optional only so the error says why). Paid:
    # the leg (a negative one-sided `transfer`) is written on it. Scheduled:
    # the account the debit will hit; nothing is written until confirmed.
    account_id: UUID | None = None
    category_id: UUID | None = None

    @model_validator(mode="after")
    def _check(self) -> "TaxPaymentCreate":
        check_component_kind(self.component, self.kind)
        return self


class TaxPaymentUpdate(BaseModel):
    paid_on: date_ | None = None
    fiscal_year: int | None = Field(default=None, ge=2000, le=2100)
    component: TaxComponent | None = None
    kind: TaxPaymentKind | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)
    # Scheduled: the account the debit will hit. Paid: moves its leg there
    # (or writes it, for one recorded without an account). Not for one linked
    # to a movement imported from the bank (409).
    account_id: UUID | None = None


class TaxPaymentExecute(BaseModel):
    """
    Confirm a scheduled payment once the debit has happened. Either link the
    movement imported from the bank statement (`transaction_id`: it becomes
    a `transfer`, since the cost was booked as a debt already), or let the
    app write the leg on the scheduled account.
    """

    paid_on: date_
    transaction_id: UUID | None = None
    category_id: UUID | None = None


class TaxPayment(BaseModel):
    id: UUID
    status: TaxPaymentStatus
    paid_on: date_
    fiscal_year: int
    component: TaxComponent
    kind: TaxPaymentKind
    amount: Decimal
    notes: str | None
    transaction_id: UUID | None
    owns_transaction: bool
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
    # Scheduled and not taken yet; `scheduled_on` is the earliest debit date.
    amount_scheduled: Decimal
    scheduled_on: date_ | None
    # True while the year (or the bollo's quarter) it's computed on hasn't closed yet.
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
    paid: Decimal  # F24 payments for this fiscal year (imposta + INPS)
    # Owed on the invoices delivered in the year (any collection state), and
    # paid for them so far.
    stamp_duty: Decimal
    stamp_duty_paid: Decimal
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
    tax_debt: Decimal  # tax_liability split in two, both ≥ 0
    tax_credit: Decimal
    cash_requirement: Decimal
    provision: ProvisionStatus
    gap: Decimal  # provision − cash_requirement
    deadlines: list[F24Deadline]
