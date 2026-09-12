/**
 * TypeScript interfaces mirroring the backend's Pydantic schemas
 * (backend/app/schemas/__init__.py). Keep these in sync manually for now —
 * if the API grows a lot, generating these from the OpenAPI schema
 * (openapi-typescript) becomes worth it, but for this size it's simpler
 * to hand-maintain.
 */

// --- Enums (mirror the Python Enum values exactly, as strings) ---

export type AccountType = 'checking' | 'savings' | 'credit_card' | 'investment' | 'crypto_wallet'
export type CategoryType = 'expense' | 'income'
export type TransactionType = 'expense' | 'income' | 'transfer'
export type TransactionSource = 'manual' | 'import'
export type BudgetPeriod = 'monthly' | 'yearly'
export type SummaryGroupBy = 'category' | 'month'

// --- Auth ---

export interface User {
  id: string
  email: string
  base_currency: string
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
  deleted_at: string | null
}

export interface CategoryCreatePayload {
  name: string
  type: CategoryType
  parent_id?: string | null
}

export interface CategoryUpdatePayload {
  name?: string
  parent_id?: string | null
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
}

export interface TransactionUpdatePayload {
  category_id?: string | null
  amount?: string
  date?: string
  description?: string | null
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
  category_id: string
  category_name: string
  period: BudgetPeriod
  amount_limit: string
  amount_spent: string
  percentage_used: number
  is_over_budget: boolean
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
