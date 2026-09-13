import { apiClient } from './client'
import type {
  AssetTransaction,
  AssetTransactionCreatePayload,
  AssetTransactionImportPreview,
  AssetTransactionUpdatePayload,
} from '@/types'

export interface AssetTransactionListParams {
  account_id?: string
  asset_id?: string
}

export async function listAssetTransactions(
  params: AssetTransactionListParams = {},
): Promise<AssetTransaction[]> {
  const { data } = await apiClient.get<AssetTransaction[]>('/portfolio/transactions', { params })
  return data
}

export async function createAssetTransaction(
  payload: AssetTransactionCreatePayload,
): Promise<AssetTransaction> {
  const { data } = await apiClient.post<AssetTransaction>('/portfolio/transactions', payload)
  return data
}

export async function updateAssetTransaction(
  id: string,
  payload: AssetTransactionUpdatePayload,
): Promise<AssetTransaction> {
  const { data } = await apiClient.patch<AssetTransaction>(`/portfolio/transactions/${id}`, payload)
  return data
}

export async function deleteAssetTransaction(id: string): Promise<void> {
  await apiClient.delete(`/portfolio/transactions/${id}`)
}

// --- CSV import (two-step: preview, then confirm) ---

export async function importAssetTransactionsPreview(
  accountId: string,
  file: File,
): Promise<AssetTransactionImportPreview> {
  const formData = new FormData()
  formData.append('file', file)

  const { data } = await apiClient.post<AssetTransactionImportPreview>(
    '/portfolio/transactions/import',
    formData,
    { params: { account_id: accountId }, headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function confirmAssetTransactionsImport(
  importId: string,
  rowNumbers: number[],
): Promise<AssetTransaction[]> {
  const { data } = await apiClient.post<AssetTransaction[]>('/portfolio/transactions/import/confirm', {
    import_id: importId,
    row_numbers: rowNumbers,
  })
  return data
}
