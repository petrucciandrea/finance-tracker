import { apiClient } from './client'
import type {
  MetalMovementPayload,
  PhysicalAssetCreatePayload,
  PhysicalAssetSellPayload,
  PhysicalAssetUpdatePayload,
  PhysicalAssetValuationPayload,
  PhysicalAssetWithValue,
} from '@/types'

const BASE = '/physical-assets'

export async function listPhysicalAssets(includeSold: boolean): Promise<PhysicalAssetWithValue[]> {
  const { data } = await apiClient.get<PhysicalAssetWithValue[]>(BASE, { params: { include_sold: includeSold } })
  return data
}

export async function createPhysicalAsset(payload: PhysicalAssetCreatePayload): Promise<PhysicalAssetWithValue> {
  const { data } = await apiClient.post<PhysicalAssetWithValue>(BASE, payload)
  return data
}

export async function updatePhysicalAsset(id: string, payload: PhysicalAssetUpdatePayload): Promise<PhysicalAssetWithValue> {
  const { data } = await apiClient.patch<PhysicalAssetWithValue>(`${BASE}/${id}`, payload)
  return data
}

export async function deletePhysicalAsset(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/${id}`)
}

export async function sellPhysicalAsset(id: string, payload: PhysicalAssetSellPayload): Promise<PhysicalAssetWithValue> {
  const { data } = await apiClient.post<PhysicalAssetWithValue>(`${BASE}/${id}/sell`, payload)
  return data
}

export async function unsellPhysicalAsset(id: string): Promise<PhysicalAssetWithValue> {
  const { data } = await apiClient.post<PhysicalAssetWithValue>(`${BASE}/${id}/unsell`)
  return data
}

export async function createValuation(id: string, payload: PhysicalAssetValuationPayload): Promise<PhysicalAssetWithValue> {
  const { data } = await apiClient.post<PhysicalAssetWithValue>(`${BASE}/${id}/valuations`, payload)
  return data
}

export async function deleteValuation(id: string, valuationId: string): Promise<PhysicalAssetWithValue> {
  const { data } = await apiClient.delete<PhysicalAssetWithValue>(`${BASE}/${id}/valuations/${valuationId}`)
  return data
}

export async function createMovement(id: string, payload: MetalMovementPayload): Promise<PhysicalAssetWithValue> {
  const { data } = await apiClient.post<PhysicalAssetWithValue>(`${BASE}/${id}/movements`, payload)
  return data
}

export async function deleteMovement(id: string, movementId: string): Promise<PhysicalAssetWithValue> {
  const { data } = await apiClient.delete<PhysicalAssetWithValue>(`${BASE}/${id}/movements/${movementId}`)
  return data
}
