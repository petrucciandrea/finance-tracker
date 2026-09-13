import { apiClient } from './client'
import type {
  AssetTransaction,
  AssetTransactionCreatePayload,
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
