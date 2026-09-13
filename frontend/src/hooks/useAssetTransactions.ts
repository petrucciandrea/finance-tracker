import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as assetTransactionsApi from '@/api/assetTransactions'
import type { AssetTransactionListParams } from '@/api/assetTransactions'
import { invalidatePortfolio } from '@/hooks/usePortfolio'
import type { AssetTransactionCreatePayload, AssetTransactionUpdatePayload } from '@/types'

export const ASSET_TRANSACTIONS_KEY = ['asset-transactions'] as const

export function useAssetTransactionsList(params: AssetTransactionListParams = {}) {
  return useQuery({
    queryKey: [...ASSET_TRANSACTIONS_KEY, params],
    queryFn: () => assetTransactionsApi.listAssetTransactions(params),
  })
}

function invalidateAssetTransactionsAndDerived(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ASSET_TRANSACTIONS_KEY })
  invalidatePortfolio(queryClient)
}

export function useCreateAssetTransaction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AssetTransactionCreatePayload) =>
      assetTransactionsApi.createAssetTransaction(payload),
    onSuccess: () => invalidateAssetTransactionsAndDerived(queryClient),
  })
}

export function useUpdateAssetTransaction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: AssetTransactionUpdatePayload }) =>
      assetTransactionsApi.updateAssetTransaction(id, payload),
    onSuccess: () => invalidateAssetTransactionsAndDerived(queryClient),
  })
}

export function useDeleteAssetTransaction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => assetTransactionsApi.deleteAssetTransaction(id),
    onSuccess: () => invalidateAssetTransactionsAndDerived(queryClient),
  })
}

export function useAssetTransactionImportPreview() {
  return useMutation({
    mutationFn: ({ accountId, file }: { accountId: string; file: File }) =>
      assetTransactionsApi.importAssetTransactionsPreview(accountId, file),
  })
}

export function useConfirmAssetTransactionImport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ importId, rowNumbers }: { importId: string; rowNumbers: number[] }) =>
      assetTransactionsApi.confirmAssetTransactionsImport(importId, rowNumbers),
    onSuccess: () => invalidateAssetTransactionsAndDerived(queryClient),
  })
}
