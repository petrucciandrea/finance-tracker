import { apiClient } from './client'
import type {
  SavingsGoal,
  WaterfallExecuteRequest,
  WaterfallExecuteResponse,
  SavingsGoalCreatePayload,
  SavingsGoalSource,
  SavingsGoalUpdatePayload,
  PillarsResponse,
  WaterfallPlan,
} from '@/types'

export async function listGoals(): Promise<SavingsGoal[]> {
  const { data } = await apiClient.get<SavingsGoal[]>('/planning/goals')
  return data
}

export async function createGoal(payload: SavingsGoalCreatePayload): Promise<SavingsGoal> {
  const { data } = await apiClient.post<SavingsGoal>('/planning/goals', payload)
  return data
}

export async function updateGoal(
  id: string,
  payload: SavingsGoalUpdatePayload,
): Promise<SavingsGoal> {
  const { data } = await apiClient.patch<SavingsGoal>(`/planning/goals/${id}`, payload)
  return data
}

export async function deleteGoal(id: string): Promise<void> {
  await apiClient.delete(`/planning/goals/${id}`)
}

export async function addSource(
  goalId: string,
  accountId: string,
  assetId?: string | null,
): Promise<SavingsGoalSource> {
  const { data } = await apiClient.post<SavingsGoalSource>(
    `/planning/goals/${goalId}/sources`,
    { account_id: accountId, asset_id: assetId ?? null },
  )
  return data
}

export async function getPillars(date?: string): Promise<PillarsResponse> {
  const { data } = await apiClient.get<PillarsResponse>('/planning/pillars', { params: { date } })
  return data
}

export async function removeSource(goalId: string, sourceId: string): Promise<void> {
  await apiClient.delete(`/planning/goals/${goalId}/sources/${sourceId}`)
}

export async function getWaterfall(date?: string): Promise<WaterfallPlan> {
  const { data } = await apiClient.get<WaterfallPlan>('/planning/waterfall', { params: { date } })
  return data
}

export async function executeWaterfall(
  payload: WaterfallExecuteRequest,
): Promise<WaterfallExecuteResponse> {
  const { data } = await apiClient.post<WaterfallExecuteResponse>(
    '/planning/waterfall/execute',
    payload,
  )
  return data
}
