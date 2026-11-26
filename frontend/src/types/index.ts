/**
 * TypeScript interfaces mirroring the backend's Pydantic schemas
 * (backend/app/schemas/__init__.py). Keep these in sync manually for now —
 * if the API grows a lot, generating these from the OpenAPI schema
 * (openapi-typescript) becomes worth it, but for this size it's simpler
 * to hand-maintain.
 */

// --- Enums (mirror the Python Enum values exactly, as strings) ---

export type AccountType = 'checking' | 'savings' | 'credit_card' | 'investment' | 'crypto_wallet' | 'cash'
export type CategoryType = 'expense' | 'income' | 'transfer'
// How essential a kind of spend is, for the planning engine's allocation
// model. `null` means "not classified yet" and is reported as its own
// bucket rather than folded into 'primary'.
export type NecessityLevel = 'primary' | 'useful' | 'discretionary'
// The four slots income is split into. The first three mirror
// NecessityLevel; `savings` is the residual — what wasn't spent.
export type AllocationBucket = NecessityLevel | 'savings'
export type SavingsGoalKind = 'emergency_fund' | 'medium_term' | 'long_term'
// months_of_primary_expenses: target follows the user's real cost of living.
// open_ended: no target, absorbs the remainder and closes the cascade.
export type TargetMode = 'months_of_primary_expenses' | 'fixed_amount' | 'open_ended'
// 'transfer' is executable by the backend; 'advice' must be done by hand.
export type WaterfallActionKind = 'transfer' | 'advice'
export type TransactionType = 'expense' | 'income' | 'transfer'
export type TransactionSource = 'manual' | 'import'
export type BudgetPeriod = 'monthly' | 'yearly'
export type SummaryGroupBy = 'category' | 'month'
export type AssetType = 'stock' | 'etf' | 'crypto'
export type AssetTransactionType = 'buy' | 'sell'
export type PortfolioHistoryPeriod = '1m' | '3m' | '6m' | '1y' | 'all'

// --- Auth ---

// employee / P.IVA forfettaria / P.IVA ordinaria. Only flat_rate unlocks a
// section (Fatture) so far; null = the "Lavoro" section is off.
export type WorkType = 'employee' | 'flat_rate' | 'ordinary'

export interface User {
  id: string
  email: string
  base_currency: string
  first_name: string | null
  last_name: string | null
  date_of_birth: string | null
  hide_amounts: boolean
  work_type: WorkType | null
  approval_status: ApprovalStatus
  email_verified_at: string | null
  created_at: string
}

export type ApprovalStatus = 'pending' | 'approved' | 'rejected'

/** What the admin sees on the page the approval email links to. */
export interface ApprovalRequestInfo {
  email: string
  approval_status: ApprovalStatus
  created_at: string
}

/** What the login/register pages may offer: closed registration and no email hide dead ends. */
export interface PublicConfig {
  registration_mode: 'closed' | 'approval' | 'open'
  email_enabled: boolean
}

export interface RegisterPayload {
  email: string
  password: string
  base_currency: string
  accept_terms: boolean
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
  hide_amounts?: boolean
  work_type?: WorkType | null
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
  /** YYYY-MM-DD. A closed account keeps its balance and history but takes no movement dated after it. */
  closed_at: string | null
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
  /** A date closes the account, null reopens it. */
  closed_at?: string | null
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
  // Expense: the share paid for others (the spend counts only the rest) and how
  // much of it has come back. `repaid_amount` is null whenever `lent_amount` is.
  lent_amount: string | null
  repaid_amount: string | null
  // Income that pays back an expense: cash, not income, in every total.
  repays_transaction_id: string | null
  // The other leg of a credit settled in kind (spend ↔ repayment), when there is one.
  offset_transaction_id: string | null
  // The other leg of a giroconto, when there is one. Null on every opening
  // balance and portfolio cash leg — read it as "may have".
  counterpart_transaction_id: string | null
  // The other leg's account, so a merged giroconto can read "A → B".
  counterpart_account_id: string | null
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
  lent_amount?: string | null
  repays_transaction_id?: string | null
}

// A credit settled in kind (the friend paid the next time): the backend writes
// the user's own spend and the repayment closing the credit, on one account, so
// cash doesn't move. Returns [spend, repayment]; `amount` is the positive magnitude.
export interface CreditOffsetCreatePayload {
  credit_transaction_id: string
  account_id: string
  // An expense category for the user's share; none falls back to "Varie".
  category_id?: string | null
  amount: string
  date: string
  description?: string | null
  necessity_level_override?: NecessityLevel | null
}

// A giroconto: the backend writes both legs (negative out, positive in) and
// links them, so `amount` is the positive magnitude.
export interface TransferCreatePayload {
  from_account_id: string
  to_account_id: string
  // A transfer-type category, or none (transfers never fall into "Varie").
  category_id?: string | null
  amount: string
  date: string
  description?: string | null
}

export interface TransactionUpdatePayload {
  category_id?: string | null
  amount?: string
  date?: string
  description?: string | null
  necessity_level_override?: NecessityLevel | null
  // null clears it (refused while repayments exist).
  lent_amount?: string | null
  repays_transaction_id?: string | null
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
  // One row per linked giroconto (its outgoing leg); ignored with account_id.
  merge_transfer_legs?: boolean
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
  // Filed on the cash-side transfer row; transfer-type categories only.
  category_id?: string | null
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
  // Vehicles and precious metals: in net worth, never in cash.
  total_physical_assets_value: string
  // Taxes accrued on collected P.IVA income, net of F24 payments; already
  // subtracted from total_net_worth. Negative = a credit (advances paid ahead).
  total_tax_liability: string
  // The same, split (both ≥ 0, debt − credit = total_tax_liability). The year
  // in progress stays gross (accrued = debt, its advances = credit) until it closes.
  total_tax_debt: string
  total_tax_credit: string
  // Money fronted for others and not yet paid back: in net worth, never in cash.
  total_credits_value: string
  accounts: AccountBalance[]
  holdings: HoldingWithValue[]
  physical_assets: PhysicalAssetWithValue[]
}

export interface PortfolioHistoryPoint {
  date: string
  total_holdings_value_base_currency: string
  total_cash_balance_base_currency: string
  total_physical_assets_value_base_currency: string
  total_credits_base_currency: string
  total_liabilities_base_currency: string
  total_net_worth: string
}

export interface PortfolioHistoryResponse {
  base_currency: string
  points: PortfolioHistoryPoint[]
}

// --- Physical assets (vehicles, precious metals) ---

export type PhysicalAssetKind = 'vehicle' | 'metal'
export type VehicleType = 'car' | 'motorcycle' | 'other'
export type PreciousMetal = 'gold' | 'silver' | 'platinum'
export type MetalForm = 'bullion' | 'coin' | 'jewelry'

export type MetalMovementType = 'buy' | 'sell'

export interface MetalMovement {
  id: string
  type: MetalMovementType
  date: string
  weight_grams: string
  price: string | null
  price_base_currency: string | null
  account_id: string | null
  notes: string | null
}

export interface MetalMovementPayload {
  type: MetalMovementType
  date: string
  weight_grams: string
  price?: string | null
  account_id?: string | null
  category_id?: string | null
  notes?: string | null
}

export interface PhysicalAssetValuation {
  id: string
  date: string
  value: string
  notes: string | null
}

export interface PhysicalAssetWithValue {
  id: string
  kind: PhysicalAssetKind
  name: string
  notes: string | null
  currency: string
  purchase_date: string
  purchase_price: string | null
  purchase_price_base_currency: string | null
  purchase_account_id: string | null
  sold_at: string | null
  sale_price: string | null
  sale_price_base_currency: string | null
  sale_account_id: string | null
  vehicle_type: VehicleType | null
  depreciation_rate: string | null
  valuations: PhysicalAssetValuation[]
  metal: PreciousMetal | null
  metal_form: MetalForm | null
  // A metal is a position: grams held today, built from its movements. Its
  // purchase_date is the first buy, purchase_price_base_currency the average
  // cost of the grams held, sold_at the last sale once nothing is left.
  weight_grams: string | null
  purity: string | null
  movements: MetalMovement[]
  fine_weight_grams: string | null
  spot_price_per_gram_base_currency: string | null
  // null when it can't be priced today, and once sold — never "0".
  current_value_base_currency: string | null
  value_date: string
  pnl_base_currency: string | null
  // Metal only: gain on grams already sold, at average cost.
  realized_pnl_base_currency: string | null
  created_at: string
}

export interface PhysicalAssetCreatePayload {
  kind: PhysicalAssetKind
  name: string
  notes?: string | null
  currency: string
  purchase_date: string
  purchase_price?: string | null
  account_id?: string | null
  category_id?: string | null
  vehicle_type?: VehicleType
  depreciation_rate?: string
  metal?: PreciousMetal
  metal_form?: MetalForm
  weight_grams?: string
  purity?: string
}

export interface PhysicalAssetUpdatePayload {
  name?: string
  notes?: string | null
  // On a metal this re-dates its first buy movement (and that buy's cash leg).
  purchase_date?: string
  // Vehicle only: a metal's prices are its movements.
  purchase_price?: string | null
  vehicle_type?: VehicleType
  depreciation_rate?: string
  metal_form?: MetalForm
  purity?: string
}

export interface PhysicalAssetSellPayload {
  sold_at: string
  sale_price: string
  account_id?: string | null
  category_id?: string | null
}

export interface PhysicalAssetValuationPayload {
  date: string
  value: string
  notes?: string | null
}

// --- Planning (allocation model, survival budget, simulator) ---

export interface AllocationPlan {
  id: string
  pct_primary: string
  pct_useful: string
  pct_discretionary: string
  pct_savings: string
  lookback_months: number
  // Pillar 1's target: months of average total spend.
  operating_cash_months: string
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
  operating_cash_months?: string
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
  // The plan's base: gross income minus imposta + INPS on the P.IVA
  // invoices collected in the month.
  income_total: string
  gross_income_total: string
  flat_rate_tax_total: string
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

// --- Savings goals and the waterfall ---

export interface SavingsGoalSource {
  id: string
  account_id: string
  // Set = that holding inside the account (valued from the cached price).
  asset_id: string | null
  asset: Asset | null
}

export interface SavingsGoal {
  id: string
  name: string
  kind: SavingsGoalKind
  priority: number
  target_mode: TargetMode
  target_months: string | null
  target_amount: string | null
  // medium_term + fixed_amount only.
  target_date: string | null
  // Reached and spent: out of the cascade, sources retired.
  completed_at: string | null
  sources: SavingsGoalSource[]
  deleted_at: string | null
}

export interface SavingsGoalCreatePayload {
  name: string
  kind: SavingsGoalKind
  // Omitted = placed by the server (a dated goal by its date).
  priority?: number
  target_mode: TargetMode
  target_months?: string | null
  target_amount?: string | null
  target_date?: string | null
}

export interface SavingsGoalUpdatePayload {
  name?: string
  priority?: number
  target_mode?: TargetMode
  target_months?: string | null
  target_amount?: string | null
  target_date?: string | null
  completed_at?: string | null
}

export interface WaterfallStep {
  goal_id: string
  name: string
  kind: SavingsGoalKind
  priority: number
  target_mode: TargetMode
  // null while a dynamic target can't be computed. Such a rung is skipped,
  // never shown as funded.
  target_amount: string | null
  target_unavailable: boolean
  current_amount: string
  gap: string
  allocated_amount: string
  funding_percentage: number
  is_funded: boolean
  // A holding source without a cached price: current_amount leaves it out.
  has_unpriced_sources: boolean
  // Dated goals only.
  target_date: string | null
  months_left: number | null
  // This month: executed giroconti + pending suggestion (one-off surplus included).
  this_month_amount: string | null
  // From next month: the rate still needed, and what the monthly quota alone brings.
  required_monthly: string | null
  monthly_pace: string | null
  projected_date: string | null
  on_track: boolean | null
}

export interface WaterfallAction {
  kind: WaterfallActionKind
  // null for the tax provision rung (purpose 'tax_provision').
  goal_id: string | null
  goal_name: string
  purpose: 'goal' | 'tax_provision'
  amount: string
  currency: string
  from_account_id: string | null
  from_account_name: string | null
  to_account_id: string | null
  to_account_name: string | null
  reason: string
}

// --- The plan's four pillars ---

export type PillarKey = 'operating' | 'emergency' | 'planned' | 'investing'
export type PillarItemKind = 'tax_provision' | 'vehicle_deadline' | 'uninvested_cash' | 'free_holdings' | 'goal_account_excess'

export interface PillarItem {
  kind: PillarItemKind
  label: string
  amount: string | null
  available: string | null
  currency: string
  due_date: string | null
  monthly: string | null
  account_name: string | null
}

export interface Pillar {
  key: PillarKey
  target: string | null
  current: string
  gap: string | null
  monthly_required: string | null
  steps: WaterfallStep[]
  items: PillarItem[]
}

export interface PillarsResponse {
  base_currency: string
  period_start: string
  operating_cash_months: string
  monthly_total_expenses: string | null
  has_unpriced_holdings: boolean
  pillars: Pillar[]
}

export interface WaterfallExecutionItem {
  // A goal, or (to_account_id) the tax provision's account.
  goal_id?: string
  to_account_id?: string
  from_account_id: string
  amount: string
}

export interface WaterfallExecuteRequest {
  date?: string
  items: WaterfallExecutionItem[]
}

export interface SavingsAllocation {
  id: string
  goal_id: string
  transaction_id: string
  period_start: string
  amount_base_currency: string
  created_at: string
}

export interface WaterfallExecuteResponse {
  allocations: SavingsAllocation[]
  transactions: Transaction[]
}

export interface WaterfallPlan {
  base_currency: string
  period_start: string
  period_end: string
  income_total: string // net of flat-rate taxes
  gross_income_total: string
  flat_rate_tax_total: string
  savings_quota: string
  already_allocated: string
  steps: WaterfallStep[]
  unallocated_amount: string
  actions: WaterfallAction[]
  // Operating accounts beyond pillar 1's target and their scheduled debits; null without history.
  operating_surplus: string | null
  // What was distributed: the larger of the quota left and the surplus (never their sum).
  budget: string
  tax_provision: TaxProvisionRung | null
  // The plan's account, or (none in the plan) the operating account with the most cash.
  source_account_id: string | null
  source_is_fallback: boolean
  // What goal accounts hold beyond every goal they fund (shared accounts are
  // split in priority order): moved on by the cascade, from those accounts.
  goal_account_excess: string
  goal_account_excesses: { account_id: string; account_name: string; amount: string }[]
}

export interface TaxProvisionRung {
  target: string
  current: string
  gap: string
  allocated_amount: string
  account_id: string | null
  account_name: string | null
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

// --- P.IVA forfettaria (amounts in EUR) ---

export type TaxComponent = 'substitute_tax' | 'inps' | 'stamp_duty'
// q1–q4 are the bollo's quarters; the taxes use saldo/acconti.
export type TaxPaymentKind = 'balance' | 'first_advance' | 'second_advance' | 'q1' | 'q2' | 'q3' | 'q4'
// scheduled = authorised (a direct debit on the AdE portal), not taken yet: moves nothing.
export type TaxPaymentStatus = 'scheduled' | 'paid'
export type InvoiceStatus = 'collected' | 'outstanding'

export interface FlatRateSettings {
  activity_start_date: string | null
  safety_margin: string
}

export interface FlatRateSettingsUpdatePayload {
  activity_start_date?: string | null
  safety_margin?: string
}

export interface FlatRateYear {
  year: number
  profitability_coefficient: string
  // Resolved: the override, else 5% within the first five years and 15% after.
  substitute_tax_rate: string
  substitute_tax_rate_is_automatic: boolean
  // Last year of the 5% start-up rate; null without a start date.
  startup_last_year: number | null
  inps_rate: string
  rivalsa_rate: string
  // The user's explicit choice; null = follow the suggestion.
  provision_rate: string | null
  // coefficient × (tax + INPS): what a euro collected owes for its own year.
  load_rate: string
  // coefficient × (tax + 80% INPS): the advances it commits next year to.
  advance_rate: string
  needed_rate: string
  suggested_provision_rate: string
  effective_provision_rate: string
  // Only in the activity's second year: after the first declaration (30 June)
  // the suggestion drops to the steady rate. See lib/flatRate.ts:provisionRateOn.
  provision_switch_date: string | null
  suggested_provision_rate_after_switch: string | null
}

export interface FlatRateYearUpdatePayload {
  profitability_coefficient?: string
  // null = back to automatic
  substitute_tax_rate?: string | null
  inps_rate?: string
  rivalsa_rate?: string
  provision_rate?: string | null
}

export interface Invoice {
  id: string
  number: string | null
  client: string
  issue_date: string
  collected_on: string | null
  amount: string
  rivalsa_rate: string
  rivalsa_amount: string
  stamp_duty: boolean
  stamp_duty_amount: string
  // When SdI delivered it, if not the issue date: the bollo's quarter follows it.
  sdi_delivered_on: string | null
  total: string
  // The collection year once collected, the issue year until then.
  fiscal_year: number
  provision_rate: string | null
  applied_provision_rate: string
  // Per-invoice estimate, gross of the INPS deduction.
  taxable_base: string
  substitute_tax: string
  inps: string
  substitute_tax_advance: string
  inps_advance: string
  to_provision: string
  transaction_id: string | null
  owns_transaction: boolean
  transaction_account_id: string | null
  transaction_deleted: boolean
  notes: string | null
  created_at: string
}

export interface InvoiceCreatePayload {
  number?: string | null
  client: string
  issue_date: string
  amount: string
  rivalsa_rate?: string | null
  // null/omitted = automatic above €77,47
  stamp_duty?: boolean | null
  sdi_delivered_on?: string | null
  provision_rate?: string | null
  notes?: string | null
}

// collected_on re-dates a collection; undoing one is /uncollect.
export type InvoiceUpdatePayload = Partial<InvoiceCreatePayload> & { collected_on?: string }

export interface InvoiceCollectPayload {
  collected_on: string
  transaction_id?: string | null
  account_id?: string | null
  category_id?: string | null
}

export interface TaxPayment {
  id: string
  status: TaxPaymentStatus
  // For a scheduled one: the day the debit is expected.
  paid_on: string
  fiscal_year: number
  component: TaxComponent
  kind: TaxPaymentKind
  amount: string
  notes: string | null
  transaction_id: string | null
  // false = a movement imported from the bank, linked on confirmation.
  owns_transaction: boolean
  account_id: string | null
  created_at: string
}

export interface TaxPaymentCreatePayload {
  paid_on: string
  fiscal_year: number
  component: TaxComponent
  kind: TaxPaymentKind
  amount: string
  notes?: string | null
  status?: TaxPaymentStatus
  // The account it left (paid) or will leave (scheduled): required, 422 without.
  account_id: string
  category_id?: string | null
}

// account_id: scheduled payments only.
export type TaxPaymentUpdatePayload = Partial<Omit<TaxPaymentCreatePayload, 'category_id' | 'status'>>

export interface TaxPaymentExecutePayload {
  paid_on: string
  // Link the debit imported from the bank, or omit to write it on the scheduled account.
  transaction_id?: string | null
  category_id?: string | null
}

export interface ProvisionSource {
  id: string
  account_id: string
  account_name: string
  account_currency: string
  // null = the account's cash; set = that product held in the account.
  asset: Asset | null
  quantity: string | null
  price: string | null
  value_base_currency: string | null
  // Whole units the same account's cash could buy (products sold in whole shares).
  buyable_units: number | null
}

export interface ProvisionStatus {
  total_base_currency: string
  sources: ProvisionSource[]
}

export interface ProvisionSourceCreatePayload {
  account_id: string
  asset_id?: string | null
}

export interface F24Deadline {
  due_date: string
  fiscal_year: number
  component: TaxComponent
  kind: TaxPaymentKind
  amount_due: string
  amount_paid: string
  // Scheduled and not taken yet; scheduled_on is the earliest debit date.
  amount_scheduled: string
  scheduled_on: string | null
  // Computed on a year (or, for the bollo, a quarter) that hasn't closed yet.
  is_estimate: boolean
}

export interface FlatRateYearFigures {
  revenue: string
  revenue_limit: string
  taxable_base: string
  inps: string
  inps_deducted: string
  substitute_tax: string
  liability: string
  advances_due: string
  paid: string
  // Owed on the invoices delivered in the year, and paid for them so far.
  stamp_duty: string
  stamp_duty_paid: string
  to_provision: string
  outstanding: string
  invoice_count: number
}

export type VehicleDeadlineKind = 'insurance' | 'road_tax' | 'inspection' | 'service' | 'other'

export interface VehicleDeadline {
  id: string
  physical_asset_id: string
  kind: VehicleDeadlineKind
  label: string | null
  due_date: string
  amount: string | null
  // The account's currency when there is one, else the vehicle's.
  currency: string
  // Paid from this account: the amount is a commitment on it until done.
  account_id: string | null
  notes: string | null
  done_on: string | null
  created_at: string
}

export interface VehicleDeadlineCreatePayload {
  physical_asset_id: string
  kind: VehicleDeadlineKind
  label?: string | null
  due_date: string
  amount?: string | null
  account_id?: string | null
  notes?: string | null
}

export type VehicleDeadlineUpdatePayload = Partial<Omit<VehicleDeadlineCreatePayload, 'physical_asset_id'>>

export interface VehicleDeadlineCompletePayload {
  done_on: string
  // Set = create the next occurrence too.
  next_due_date?: string | null
}

export type AlertKind =
  | 'account_short'
  | 'account_near'
  | 'f24_overdue'
  | 'f24_upcoming'
  | 'scheduled_unconfirmed'
  | 'vehicle_overdue'
  | 'vehicle_upcoming'
  | 'goal_overdue'
  | 'goal_due_soon'
  | 'goal_behind_schedule'
  | 'goal_horizon_mismatch'
  | 'allocation_out_of_band'
  | 'allocation_over_cap'
  | 'excess_cash'
  | 'below_min_invested_share'
  | 'investing_without_emergency_fund'
  | 'exposure_data_stale'

/** Structured, so the client words it and formatAmount masks the figures. */
export interface Alert {
  // Stable while the cause is unchanged: a dismissal is remembered by it.
  id: string
  kind: AlertKind
  tone: 'danger' | 'warn'
  // every_visit: back on each app open until solved. once: dismissed for good (until the id changes).
  repeat: 'every_visit' | 'once'
  label: string
  due_date: string | null
  amount: string | null
  currency: string | null
  account_id: string | null
  account_name: string | null
  balance: string | null
  committed: string | null
  margin: string | null
  // Plan and portfolio alerts: the share measured and the limit set (0-100).
  percentage: number | null
  limit_percentage: number | null
  dimension: string | null
  bucket: string | null
  link: string | null
}

export interface CommitmentItem {
  label: string
  due_date: string
  amount: string
}

export interface AccountCommitment {
  account_id: string
  account_name: string
  currency: string
  balance: string
  committed: string
  margin: string
  // Below threshold = close to it; below committed = not enough.
  threshold: string
  last_movement_on: string | null
  items: CommitmentItem[]
}

export interface AlertsResponse {
  alerts: Alert[]
  commitments: AccountCommitment[]
}

export interface FlatRateSummary {
  year: number
  as_of: string
  params: FlatRateYear
  figures: FlatRateYearFigures
  // As of today, across every year: the net-worth liability (negative =
  // credit) and everything the F24s will still ask, next year's advances included.
  tax_liability: string
  tax_debt: string // tax_liability split in two, both ≥ 0
  tax_credit: string
  cash_requirement: string
  provision: ProvisionStatus
  gap: string
  deadlines: F24Deadline[]
}

// --- Portfolio composition (pillar 4 only) ---

export type ExposureDimension = 'asset_class' | 'region' | 'sector' | 'currency'
export type ExposureSource = 'user' | 'reference' | 'default'

export interface ExposureWeight {
  bucket: string
  weight: string
}

export interface AssetExposureDimension {
  dimension: ExposureDimension
  // null = nothing known: the product is unclassified in this dimension.
  source: ExposureSource | null
  weights: ExposureWeight[]
  as_of: string | null
  notes: string | null
  source_urls: string[]
}

export interface AssetExposures {
  asset: Asset
  dimensions: AssetExposureDimension[]
}

export interface AssetExposureUpdatePayload {
  weights: ExposureWeight[]
  as_of?: string | null
  notes?: string | null
}

export interface ExposureSuggestion {
  asset_id: string
  raw_sector: string | null
  raw_country: string | null
  weights: Partial<Record<ExposureDimension, ExposureWeight[]>>
}

export interface AllocationBucketValue {
  bucket: string
  value: string
  percentage: number
}

export interface AllocationPosition {
  kind: 'holding' | 'metal' | 'cash'
  label: string
  asset: Asset | null
  account_name: string | null
  value: string | null
  source: ExposureSource | null
  as_of: string | null
  weights: ExposureWeight[]
}

export interface PortfolioAllocation {
  dimension: ExposureDimension
  base_currency: string
  total: string
  classified_value: string
  coverage: number
  buckets: AllocationBucketValue[]
  unclassified_value: string
  // Holdings funding the emergency fund, a dated goal or the tax provision.
  excluded_value: string
  // Left out of total: non-equity for sectors, no region (gold, crypto) for regions.
  outside_value: string
  has_unpriced: boolean
  stale_count: number
  positions: AllocationPosition[]
}

// --- Pillar-4 guardrails ---

export type PortfolioRuleKind = 'target' | 'max_share' | 'excess_cash' | 'min_invested'
export type RuleState = 'ok' | 'over' | 'under' | 'unknown'

export interface PortfolioRule {
  id: string
  kind: PortfolioRuleKind
  // target: asset_class | region. max_share: any dimension, or 'position' (bucket = asset id).
  dimension: string | null
  bucket: string | null
  target_pct: string | null
  tolerance_pct: string | null
  max_pct: string | null
  min_pct: string | null
  threshold_amount: string | null
  threshold_months: string | null
}

export type PortfolioRuleCreatePayload = Omit<Partial<PortfolioRule>, 'id'> & { kind: PortfolioRuleKind }

export interface PortfolioRuleStatus {
  rule: PortfolioRule
  state: RuleState
  actual_pct: number | null
  actual_amount: string | null
  limit_amount: string | null
  reason: 'coverage' | 'no_history' | 'nothing_invested' | null
  label: string | null
}

export interface PortfolioRulesStatus {
  base_currency: string
  rules: PortfolioRuleStatus[]
  idle_cash: string | null
  invested: string
  invested_share: number | null
  contribution: string
  contribution_split: { bucket: string; amount: string }[]
}

export interface PortfolioPreset {
  key: string
  label: string
  description: string
  targets: { dimension: ExposureDimension; bucket: string; target_pct: string }[]
}

// Every target of one dimension at once (the slider editor). 0 = no target.
export interface TargetsReplacePayload {
  dimension: 'asset_class' | 'region'
  tolerance_pct?: string
  targets: { bucket: string; target_pct: string }[]
}
