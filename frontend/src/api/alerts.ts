import { apiClient } from './client'
import type { AlertsResponse } from '@/types'

export async function getAlerts(): Promise<AlertsResponse> {
  const { data } = await apiClient.get<AlertsResponse>('/alerts')
  return data
}
