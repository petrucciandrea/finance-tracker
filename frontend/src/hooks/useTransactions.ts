import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as transactionsApi from '@/api/transactions'
import type { TransactionCreatePayload, TransactionListParams, TransactionSummaryParams } from '@/types'

const TRANSACTIONS_KEY = ['transactions'] as const

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
    onSuccess: () => {
      // Both the list and any summary views depend on this data — broad
      // invalidation is simplest and correct at this app's scale.
      queryClient.invalidateQueries({ queryKey: TRANSACTIONS_KEY })
    },
  })
}

export function useDeleteTransaction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => transactionsApi.deleteTransaction(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TRANSACTIONS_KEY })
    },
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TRANSACTIONS_KEY })
    },
  })
}
