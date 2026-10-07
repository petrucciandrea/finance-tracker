import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as transactionsApi from '@/api/transactions'
import { BUDGETS_STATUS_KEY } from '@/hooks/useBudgets'
import { PLANNING_KEY } from '@/hooks/usePlanning'
import { NET_WORTH_KEY } from '@/hooks/usePortfolio'
import type {
  TransactionCreatePayload,
  TransactionListParams,
  TransactionSummaryParams,
  TransactionUpdatePayload,
} from '@/types'

// Exported so useAccounts.ts can invalidate it too — creating an account
// with a starting_balance creates an opening-balance transaction server-side.
export const TRANSACTIONS_KEY = ['transactions'] as const

// Budget spend and net worth's cash balance are both computed from
// transactions but cached under their own top-level keys ('budgets' /
// 'net-worth', not 'transactions') — invalidating TRANSACTIONS_KEY alone
// would leave both stale up to the global 30s staleTime.
function invalidateTransactionsAndDerived(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: TRANSACTIONS_KEY })
  queryClient.invalidateQueries({ queryKey: BUDGETS_STATUS_KEY })
  // The allocation model, the survival budget and the waterfall are all
  // computed from transactions, under their own top-level key.
  queryClient.invalidateQueries({ queryKey: PLANNING_KEY })
  queryClient.invalidateQueries({ queryKey: NET_WORTH_KEY })
  // The portfolio value-over-time chart's cash-balance series is also
  // derived from cash transactions.
  queryClient.invalidateQueries({ queryKey: ['portfolio-history'] })
}

export function useTransactionSummary(params: TransactionSummaryParams) {
  return useQuery({
    queryKey: [...TRANSACTIONS_KEY, 'summary', params],
    queryFn: () => transactionsApi.getSummary(params),
  })
}

export function useTransactionsList(params: TransactionListParams) {
  return useQuery({
    queryKey: [...TRANSACTIONS_KEY, 'list', params],
    queryFn: () => transactionsApi.listTransactions(params),
  })
}

export function useCreateTransaction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: TransactionCreatePayload) => transactionsApi.createTransaction(payload),
    // Both the list and any summary views depend on this data — broad
    // invalidation is simplest and correct at this app's scale.
    onSuccess: () => invalidateTransactionsAndDerived(queryClient),
  })
}

export function useUpdateTransaction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: TransactionUpdatePayload }) =>
      transactionsApi.updateTransaction(id, payload),
    // A new category or necessity override moves the plan; a new amount or
    // date moves balances too.
    onSuccess: () => invalidateTransactionsAndDerived(queryClient),
  })
}

export function useDeleteTransaction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => transactionsApi.deleteTransaction(id),
    onSuccess: () => invalidateTransactionsAndDerived(queryClient),
  })
}

export function useImportPreview() {
  return useMutation({
    mutationFn: ({ accountId, file }: { accountId: string; file: File }) =>
      transactionsApi.importPreview(accountId, file),
  })
}

export function useConfirmImport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ importId, rowNumbers }: { importId: string; rowNumbers: number[] }) =>
      transactionsApi.confirmImport(importId, rowNumbers),
    onSuccess: () => invalidateTransactionsAndDerived(queryClient),
  })
}
