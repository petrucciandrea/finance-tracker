import type { AmountKind } from '@/components/ui/Amount'
import { toNumber } from '@/lib/format'
import type { Account, Transaction } from '@/types'

export function amountKind(transaction: Pick<Transaction, 'type'>): AmountKind {
  return transaction.type
}

/**
 * The account column for a row. A linked giroconto is listed once, so it
 * names both sides; which side `account_id` is depends on the leg shown
 * (the incoming one under a destination-account filter).
 */
export function accountLabel(
  transaction: Pick<Transaction, 'account_id' | 'amount' | 'counterpart_account_id'>,
  accounts: Map<string, Account>,
): string {
  const name = (id: string) => accounts.get(id)?.name ?? 'Conto eliminato'
  if (!transaction.counterpart_account_id) return name(transaction.account_id)
  const outgoing = Number(transaction.amount) < 0
  const [from, to] = outgoing
    ? [transaction.account_id, transaction.counterpart_account_id]
    : [transaction.counterpart_account_id, transaction.account_id]
  return `${name(from)} → ${name(to)}`
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
