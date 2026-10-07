import { addMonths, endOfMonth, startOfMonth } from '@/lib/dates'
import { formatMonthYear, toISODate } from '@/lib/format'
import type { TransactionType } from '@/types'

// Filters live in the URL so links like /transactions?q=… work and the
// browser's back button undoes a filter change.

export type PeriodKey = 'month' | 'prev' | '3m' | 'year' | 'all'

export const PERIOD_LABELS: Record<PeriodKey, string> = {
  month: 'Questo mese',
  prev: 'Mese scorso',
  '3m': 'Ultimi 3 mesi',
  year: "Quest'anno",
  all: 'Tutto',
}

export const DEFAULT_PERIOD: PeriodKey = 'month'
export const PAGE_SIZES = [25, 50, 100] as const

export interface TransactionFilters {
  q: string
  period: PeriodKey
  account: string
  category: string
  currency: string
  type: TransactionType | ''
  // Only rows still in the "Varie" fallback.
  misc: boolean
  page: number
  size: number
}

export function readFilters(params: URLSearchParams): TransactionFilters {
  const period = params.get('period') as PeriodKey | null
  const type = params.get('type')
  const size = Number(params.get('size'))
  return {
    q: params.get('q') ?? '',
    period: period && period in PERIOD_LABELS ? period : DEFAULT_PERIOD,
    account: params.get('account') ?? '',
    category: params.get('category') ?? '',
    currency: params.get('currency') ?? '',
    type: type === 'expense' || type === 'income' || type === 'transfer' ? type : '',
    misc: params.get('misc') === '1',
    page: Math.max(1, Number(params.get('page')) || 1),
    size: (PAGE_SIZES as readonly number[]).includes(size) ? size : 25,
  }
}

/** Range for a period, relative to `today`. 'all' is unbounded. */
export function periodRange(period: PeriodKey, today: Date): { date_from?: string; date_to?: string } {
  switch (period) {
    case 'month':
      return { date_from: toISODate(startOfMonth(today)), date_to: toISODate(endOfMonth(today)) }
    case 'prev': {
      const prev = addMonths(today, -1)
      return { date_from: toISODate(prev), date_to: toISODate(endOfMonth(prev)) }
    }
    case '3m':
      return { date_from: toISODate(addMonths(today, -2)), date_to: toISODate(endOfMonth(today)) }
    case 'year':
      return { date_from: `${today.getFullYear()}-01-01`, date_to: `${today.getFullYear()}-12-31` }
    case 'all':
      return {}
  }
}

/** "ottobre 2026", "settembre 2026", "ultimi 3 mesi", … for the page subtitle. */
export function periodPhrase(period: PeriodKey, today: Date): string {
  if (period === 'month') return `in ${formatMonthYear(today).toLowerCase()}`
  if (period === 'prev') return `in ${formatMonthYear(addMonths(today, -1)).toLowerCase()}`
  if (period === 'year') return `nel ${today.getFullYear()}`
  if (period === '3m') return 'negli ultimi 3 mesi'
  return 'in totale'
}
