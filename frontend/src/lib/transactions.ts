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

/**
 * An expense's own share in base currency (negative). What was fronted for
 * others is a credit, not spend — same frozen rate, same fraction as the
 * backend's net_expense_base.
 */
export function ownShareBase(tx: Pick<Transaction, 'type' | 'amount' | 'amount_base_currency' | 'lent_amount'>): number {
  const base = toNumber(tx.amount_base_currency)
  if (tx.type !== 'expense' || tx.lent_amount === null) return base
  const amount = Math.abs(toNumber(tx.amount))
  return amount ? base * ((amount - toNumber(tx.lent_amount)) / amount) : base
}

export interface TransactionTotals {
  count: number
  income: number // repayments of fronted money are not income
  expense: number // negative, own share only
  repaid: number // cash that came back for fronted money (neither income nor spend)
  repaidCount: number
  // Real movements (non-transfer) as they hit the accounts, repayments included.
  cashNet: number
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
    repaid: 0,
    repaidCount: 0,
    cashNet: 0,
    transfer: 0,
    incomeCount: 0,
    expenseCount: 0,
    transferCount: 0,
    net: 0,
  }
  for (const tx of transactions) {
    const value = toNumber(tx.amount_base_currency)
    if (tx.type !== 'transfer') t.cashNet += value
    if (tx.type === 'income' && tx.repays_transaction_id) {
      t.repaid += value
      t.repaidCount += 1
    } else if (tx.type === 'income') {
      t.income += value
      t.incomeCount += 1
    } else if (tx.type === 'expense') {
      t.expense += ownShareBase(tx)
      t.expenseCount += 1
    } else {
      t.transfer += value
      t.transferCount += 1
    }
  }
  t.net = t.income + t.expense
  return t
}
