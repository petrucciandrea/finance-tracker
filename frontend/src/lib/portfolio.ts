import type { AccountType, AssetTransaction, AssetType, HoldingWithValue, PortfolioHistoryPeriod } from '@/types'

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  stock: 'Azioni',
  etf: 'ETF',
  crypto: 'Crypto',
}

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  checking: 'Conto corrente',
  savings: 'Risparmio',
  credit_card: 'Carta di credito',
  investment: 'Investimento',
  crypto_wallet: 'Wallet crypto',
  cash: 'Contanti',
}

// Accounts whose cash counts as "liquidità da investire" in the portfolio.
export const INVESTMENT_ACCOUNT_TYPES: AccountType[] = ['investment', 'crypto_wallet']

/**
 * Rate the backend used for this holding's base value. P&L arrives in the
 * asset's own currency, so converting it with this rate gives today's
 * base-currency figure (the cost basis is not re-priced historically).
 */
function holdingRate(holding: HoldingWithValue): number {
  const native = Number(holding.market_value)
  return native ? Number(holding.market_value_base_currency) / native : 1
}

export function unrealizedPnlBase(holding: HoldingWithValue): number {
  return Number(holding.unrealized_pnl) * holdingRate(holding)
}

export function realizedPnlBase(holding: HoldingWithValue): number {
  return Number(holding.realized_pnl) * holdingRate(holding)
}

export function costBasisBase(holding: HoldingWithValue): number {
  return Number(holding.market_value_base_currency) - unrealizedPnlBase(holding)
}

// Fixed order → fixed colour per asset class, whatever subset is present.
export const ALLOCATION_SERIES: { key: AssetType | 'cash'; label: string; color: string }[] = [
  { key: 'stock', label: 'Azioni', color: 'var(--color-s1)' },
  { key: 'etf', label: 'ETF', color: 'var(--color-s2)' },
  { key: 'crypto', label: 'Crypto', color: 'var(--color-s3)' },
  { key: 'cash', label: 'Liquidità', color: 'var(--color-s4)' },
]

export const PERIOD_OPTIONS: { value: PortfolioHistoryPeriod; label: string }[] = [
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
  { value: '6m', label: '6M' },
  { value: '1y', label: '1A' },
  { value: 'all', label: 'Tutto' },
]

/** The ⋯ menu items for one operation, shared by the position history and the recent list. */
export function assetTransactionMenuItems(
  tx: AssetTransaction,
  { onEdit, onDelete }: { onEdit: (tx: AssetTransaction) => void; onDelete: (tx: AssetTransaction) => void },
) {
  return [
    { label: 'Modifica operazione', onSelect: () => onEdit(tx) },
    { label: 'Elimina operazione', tone: 'danger' as const, onSelect: () => onDelete(tx) },
  ]
}
