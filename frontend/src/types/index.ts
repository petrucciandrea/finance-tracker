/**
 * TypeScript interfaces mirroring the backend's Pydantic schemas
 * (backend/app/schemas/__init__.py). Keep these in sync manually for now —
 * if the API grows a lot, generating these from the OpenAPI schema
 * (openapi-typescript) becomes worth it, but for this size it's simpler
 * to hand-maintain.
 */

// --- Enums (mirror the Python Enum values exactly, as strings) ---

export type AccountType = 'checking' | 'savings' | 'credit_card' | 'investment' | 'crypto_wallet'
export type CategoryType = 'expense' | 'income' | 'transfer'
// How essential a kind of spend is, for the planning engine's allocation
// model. `null` means "not classified yet" and is reported as its own
// bucket rather than folded into 'primary'.
export type NecessityLevel = 'primary' | 'useful' | 'discretionary'
// The four slots income is split into. The first three mirror
// NecessityLevel; `savings` is the residual — what wasn't spent.
export type AllocationBucket = NecessityLevel | 'savings'
export type TransactionType = 'expense' | 'income' | 'transfer'
export type TransactionSource = 'manual' | 'import'
export type BudgetPeriod = 'monthly' | 'yearly'
export type SummaryGroupBy = 'category' | 'month'
export type AssetType = 'stock' | 'etf' | 'crypto'
export type AssetTransactionType = 'buy' | 'sell'
export type PortfolioHistoryPeriod = '1m' | '3m' | '6m' | '1y' | 'all'

// --- Auth ---

export interface User {
  id: string
  email: string
  base_currency: string
  first_name: string | null
  last_name: string | null
  date_of_birth: string | null
  created_at: string
}

export interface RegisterPayload {
  email: string
  password: string
  base_currency: string
}

export interface LoginPayload {
  email: string
  password: string
}

export interface UserUpdatePayload {
  email?: string
  base_currency?: string
  first_name?: string | null
  last_name?: string | null
  date_of_birth?: string | null
}

export interface PasswordChangePayload {
  current_password: string
  new_password: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

// --- Accounts ---

export interface Account {
  id: string
  name: string
  type: AccountType
  currency: string
  created_at: string
  deleted_at: string | null
}

export interface AccountCreatePayload {
  name: string
  type: AccountType
  currency: string
  starting_balance?: string
}

export interface AccountUpdatePayload {
  name?: string
  type?: AccountType
}

// --- Categories ---

export interface Category {
  id: string
  name: string
  type: CategoryType
  parent_id: string | null
  // Expense categories only. A subcategory left null inherits its parent's
  // level — the backend resolves that, this field is the raw stored value.
  necessity_level: NecessityLevel | null
  // Income categories only. Keeps refunds/reversals out of the denominator
  // of the allocation model.
  excluded_from_income_base: boolean
  deleted_at: string | null
}

export interface CategoryCreatePayload {
  name: string
  type: CategoryType
  parent_id?: string | null
  necessity_level?: NecessityLevel | null
  excluded_from_income_base?: boolean
}

export interface CategoryUpdatePayload {
  name?: string
  parent_id?: string | null
  necessity_level?: NecessityLevel | null
  excluded_from_income_base?: boolean
}

// --- Transactions ---

export interface Transaction {
  id: string
  account_id: string
  category_id: string | null
  amount: string // Decimal serialized as string by the API — parse with Number() only for display math
  currency: string
  amount_base_currency: string
  exchange_rate: string
  date: string // "YYYY-MM-DD"
  description: string | null
  type: TransactionType
  source: TransactionSource
  // Expense transactions only. Wins over the category's level and the one
  // inherited from its parent.
  necessity_level_override: NecessityLevel | null
  created_at: string
  deleted_at: string | null
}

export interface TransactionCreatePayload {
  account_id: string
  category_id?: string | null
  amount: string
  currency: string
  date: string
  description?: string | null
  type: TransactionType
  necessity_level_override?: NecessityLevel | null
}

export interface TransactionUpdatePayload {
  category_id?: string | null
  amount?: string
  date?: string
  description?: string | null
  necessity_level_override?: NecessityLevel | null
}

export interface TransactionListParams {
  page?: number
  page_size?: number
  date_from?: string
  date_to?: string
  category_id?: string
  account_id?: string
  currency?: string
  type?: TransactionType
}

export interface PaginationMeta {
  page: number
  page_size: number
  total_items: number
  total_pages: number
}

export interface TransactionListResponse {
  data: Transaction[]
  meta: PaginationMeta
}

export interface TransactionSummaryParams {
  group_by?: SummaryGroupBy[]
  date_from?: string
  date_to?: string
  currency?: string
}

export interface TransactionSummaryItem {
  month: string | null
  category_id: string | null
  category_name: string | null
  total_amount_base_currency: string
  transaction_count: number
}

export interface TransactionSummaryResponse {
  data: TransactionSummaryItem[]
}

// --- CSV import ---

export interface TransactionImportRow {
  row_number: number
  account_id: string
  date: string
  amount: string
  currency: string
  description: string | null
  suggested_category_id: string | null
  is_duplicate: boolean
  is_parsable: boolean
  error: string | null
}

export interface TransactionImportPreview {
  import_id: string
  rows: TransactionImportRow[]
  total_rows: number
  parsable_rows: number
  duplicate_rows: number
}

// --- Budgets ---

export interface Budget {
  id: string
  category_id: string
  period: BudgetPeriod
  amount_limit: string
  start_date: string
  deleted_at: string | null
}

export interface BudgetCreatePayload {
  category_id: string
  period: BudgetPeriod
  amount_limit: string
  start_date: string
}

export interface BudgetUpdatePayload {
  amount_limit?: string
}

export interface BudgetStatus {
  budget_id: string
  category_id: string
  category_name: string
  period: BudgetPeriod
  amount_limit: string
  amount_spent: string
  percentage_used: number
  is_over_budget: boolean
}

// --- Portfolio ---

export interface Asset {
  id: string
  symbol: string
  name: string
  asset_type: AssetType
  currency: string
}

export interface AssetSearchResult {
  symbol: string
  name: string
  asset_type: AssetType
}

export interface AssetTransaction {
  id: string
  account_id: string
  asset: Asset
  type: AssetTransactionType
  quantity: string
  price: string
  fee: string
  amount_base_currency: string
  exchange_rate: string
  date: string
  notes: string | null
  created_at: string
  deleted_at: string | null
}

export interface AssetTransactionCreatePayload {
  account_id: string
  symbol: string
  asset_type: AssetType
  type: AssetTransactionType
  quantity: string
  price: string
  fee?: string
  date: string
  notes?: string | null
}

export interface AssetTransactionUpdatePayload {
  quantity?: string
  price?: string
  fee?: string
  date?: string
  notes?: string | null
}

// --- Asset transaction CSV import ---

export interface AssetTransactionImportRow {
  row_number: number
  account_id: string
  symbol: string
  asset_type: AssetType
  type: AssetTransactionType
  quantity: string
  price: string
  fee: string
  date: string
  notes: string | null
  is_duplicate: boolean
  is_parsable: boolean
  error: string | null
}

export interface AssetTransactionImportPreview {
  import_id: string
  rows: AssetTransactionImportRow[]
  total_rows: number
  parsable_rows: number
  duplicate_rows: number
}

// Not a DB row — computed from AssetTransaction history, `id` is a
// synthetic "accountId:assetId" key for a stable React key / lookup.
export interface HoldingWithValue {
  id: string
  account_id: string
  asset: Asset
  quantity: string
  avg_buy_price: string
  realized_pnl: string
  current_price: string
  price_date: string
  market_value: string
  market_value_base_currency: string
  unrealized_pnl: string
  unrealized_pnl_percentage: number
}

export interface AccountBalance {
  account_id: string
  account_name: string
  currency: string
  balance: string
  balance_base_currency: string
}

export interface NetWorthSummary {
  base_currency: string
  total_net_worth: string
  total_cash_balance: string
  total_holdings_value: string
  accounts: AccountBalance[]
  holdings: HoldingWithValue[]
}

export interface PortfolioHistoryPoint {
  date: string
  total_holdings_value_base_currency: string
  total_cash_balance_base_currency: string
  total_net_worth: string
}

export interface PortfolioHistoryResponse {
  base_currency: string
  points: PortfolioHistoryPoint[]
}

// --- Planning (allocation model, survival budget, simulator) ---

export interface AllocationPlan {
  id: string
  pct_primary: string
  pct_useful: string
  pct_discretionary: string
  pct_savings: string
  lookback_months: number
  default_source_account_id: string | null
}

export interface AllocationPlanUpdatePayload {
  // All four percentages move together — the backend 422s a partial set,
  // since the database constrains them to sum to 100.
  pct_primary?: string
  pct_useful?: string
  pct_discretionary?: string
  pct_savings?: string
  lookback_months?: number
  default_source_account_id?: string | null
}

export interface AllocationBucketStatus {
  bucket: AllocationBucket
  percentage: string
  target_amount: string
  actual_amount: string
  // target - actual. Positive is "under target": good for the three spend
  // buckets, bad for `savings`.
  deviation: string
  percentage_used: number
  is_over_target: boolean
}

export interface IncomeCategoryBreakdown {
  category_id: string | null
  category_name: string | null
  excluded_from_income_base: boolean
  total_amount_base_currency: string
}

export interface AllocationStatus {
  base_currency: string
  period_start: string
  period_end: string
  income_total: string
  buckets: AllocationBucketStatus[]
  unclassified_amount: string
  classification_coverage: number
  income_breakdown: IncomeCategoryBreakdown[]
}

export interface SurvivalBudget {
  base_currency: string
  lookback_months: number
  months_analysed: number
  // null, never 0, when there is no complete month of history yet.
  monthly_primary_expenses: string | null
  monthly_total_expenses: string | null
  monthly_income: string | null
  total_cash_balance: string
  months_of_runway: number | null
}

export interface SimulationCut {
  // Exactly one of these two.
  necessity_level?: NecessityLevel
  category_id?: string
  cut_percentage: string
}

export interface SimulationRequest {
  date?: string
  cuts: SimulationCut[]
}

export interface SimulatedBucket {
  bucket: AllocationBucket
  baseline_amount: string
  simulated_amount: string
  freed_amount: string
}

export interface SimulationResponse {
  base_currency: string
  period_start: string
  period_end: string
  income_total: string
  buckets: SimulatedBucket[]
  total_baseline_spend: string
  total_simulated_spend: string
  total_freed: string
  baseline_savings_amount: string
  simulated_savings_amount: string
  baseline_savings_rate: number
  simulated_savings_rate: number
  baseline_survival_budget: string | null
  simulated_survival_budget: string | null
}

// --- Errors (the envelope from main.py's exception handlers) ---

export interface ApiErrorDetail {
  field: string | null
  message: string
}

export interface ApiErrorResponse {
  error: {
    code: string
    message: string
    details: ApiErrorDetail[]
  }
}
