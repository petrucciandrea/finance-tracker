import type { AmountKind } from '@/components/ui/Amount'
import { toNumber } from '@/lib/format'
import type { Transaction } from '@/types'

export function amountKind(transaction: Pick<Transaction, 'type'>): AmountKind {
  return transaction.type
}

export interface TransactionTotals {
  count: number
  income: number
  expense: number // negative
  transfer: number // net, in base currency
  incomeCount: number
  expenseCount: number
  transferCount: number
  net: number
}

/** Totals in base currency (the frozen amount_base_currency, never re-converted). */
export function totals(transactions: Transaction[]): TransactionTotals {
  const t: TransactionTotals = {
    count: transactions.length,
    income: 0,
    expense: 0,
    transfer: 0,
    incomeCount: 0,
    expenseCount: 0,
    transferCount: 0,
    net: 0,
  }
  for (const tx of transactions) {
    const value = toNumber(tx.amount_base_currency)
    if (tx.type === 'income') {
      t.income += value
      t.incomeCount += 1
    } else if (tx.type === 'expense') {
      t.expense += value
      t.expenseCount += 1
    } else {
      t.transfer += value
      t.transferCount += 1
    }
  }
  t.net = t.income + t.expense
  return t
}
