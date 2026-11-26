import { apiClient } from './client'
import type {
  AssetExposures,
  AssetExposureUpdatePayload,
  ExposureDimension,
  ExposureSuggestion,
  PortfolioAllocation,
} from '@/types'

export async function getAllocation(dimension: ExposureDimension, includeCash: boolean): Promise<PortfolioAllocation> {
  const { data } = await apiClient.get<PortfolioAllocation>('/portfolio/allocation', {
    params: { dimension, include_cash: includeCash },
  })
  return data
}

export async function getExposures(assetId: string): Promise<AssetExposures> {
  const { data } = await apiClient.get<AssetExposures>(`/portfolio/assets/${assetId}/exposures`)
  return data
}

export async function putExposures(
  assetId: string,
  dimension: ExposureDimension,
  payload: AssetExposureUpdatePayload,
): Promise<AssetExposures> {
  const { data } = await apiClient.put<AssetExposures>(`/portfolio/assets/${assetId}/exposures/${dimension}`, payload)
  return data
}

export async function resetExposures(assetId: string, dimension: ExposureDimension): Promise<AssetExposures> {
  const { data } = await apiClient.delete<AssetExposures>(`/portfolio/assets/${assetId}/exposures/${dimension}`)
  return data
}

export async function getSuggestion(assetId: string): Promise<ExposureSuggestion> {
  const { data } = await apiClient.get<ExposureSuggestion>(`/portfolio/assets/${assetId}/exposure-suggestion`)
  return data
}
