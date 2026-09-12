import { apiClient } from './client'
import type {
  AssetSearchResult,
  AssetType,
  HoldingCreatePayload,
  HoldingUpdatePayload,
  HoldingWithValue,
  NetWorthSummary,
} from '@/types'

export async function searchAssets(q: string, assetType: AssetType): Promise<AssetSearchResult[]> {
  const { data } = await apiClient.get<AssetSearchResult[]>('/portfolio/assets/search', {
    params: { q, asset_type: assetType },
  })
  return data
}

export async function listHoldings(): Promise<HoldingWithValue[]> {
  const { data } = await apiClient.get<HoldingWithValue[]>('/portfolio/holdings')
  return data
}

export async function createHolding(payload: HoldingCreatePayload): Promise<HoldingWithValue> {
  const { data } = await apiClient.post<HoldingWithValue>('/portfolio/holdings', payload)
  return data
}

export async function updateHolding(
  id: string,
  payload: HoldingUpdatePayload,
): Promise<HoldingWithValue> {
  const { data } = await apiClient.patch<HoldingWithValue>(`/portfolio/holdings/${id}`, payload)
  return data
}

export async function deleteHolding(id: string): Promise<void> {
  await apiClient.delete(`/portfolio/holdings/${id}`)
}

export async function getNetWorth(): Promise<NetWorthSummary> {
  const { data } = await apiClient.get<NetWorthSummary>('/portfolio/net-worth')
  return data
}
