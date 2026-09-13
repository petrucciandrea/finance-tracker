import { apiClient } from './client'
import type {
  AssetSearchResult,
  AssetType,
  HoldingWithValue,
  NetWorthSummary,
  PortfolioHistoryPeriod,
  PortfolioHistoryResponse,
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

export async function getNetWorth(): Promise<NetWorthSummary> {
  const { data } = await apiClient.get<NetWorthSummary>('/portfolio/net-worth')
  return data
}

export async function getPortfolioHistory(
  period: PortfolioHistoryPeriod,
): Promise<PortfolioHistoryResponse> {
  const { data } = await apiClient.get<PortfolioHistoryResponse>('/portfolio/history', {
    params: { period },
  })
  return data
}
