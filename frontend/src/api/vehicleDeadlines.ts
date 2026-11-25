import { apiClient } from './client'
import type { VehicleDeadline, VehicleDeadlineCompletePayload, VehicleDeadlineCreatePayload, VehicleDeadlineUpdatePayload } from '@/types'

const BASE = '/vehicle-deadlines'

export async function listVehicleDeadlines(includeDone: boolean): Promise<VehicleDeadline[]> {
  const { data } = await apiClient.get<VehicleDeadline[]>(BASE, { params: { include_done: includeDone } })
  return data
}

export async function createVehicleDeadline(payload: VehicleDeadlineCreatePayload): Promise<VehicleDeadline> {
  const { data } = await apiClient.post<VehicleDeadline>(BASE, payload)
  return data
}

export async function updateVehicleDeadline(id: string, payload: VehicleDeadlineUpdatePayload): Promise<VehicleDeadline> {
  const { data } = await apiClient.patch<VehicleDeadline>(`${BASE}/${id}`, payload)
  return data
}

export async function completeVehicleDeadline(id: string, payload: VehicleDeadlineCompletePayload): Promise<VehicleDeadline[]> {
  const { data } = await apiClient.post<VehicleDeadline[]>(`${BASE}/${id}/complete`, payload)
  return data
}

export async function reopenVehicleDeadline(id: string): Promise<VehicleDeadline> {
  const { data } = await apiClient.post<VehicleDeadline>(`${BASE}/${id}/reopen`)
  return data
}

export async function deleteVehicleDeadline(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/${id}`)
}
