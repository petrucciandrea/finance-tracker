import { apiClient } from './client'
import type {
  AllocationPlan,
  AllocationPlanUpdatePayload,
  AllocationStatus,
  SimulationRequest,
  SimulationResponse,
  SurvivalBudget,
} from '@/types'

export async function getPlan(): Promise<AllocationPlan> {
  // Get-or-create on the backend: a first read returns the 50/25/15/10
  // preset rather than a 404, so there is no "create plan" call.
  const { data } = await apiClient.get<AllocationPlan>('/planning/plan')
  return data
}

export async function updatePlan(payload: AllocationPlanUpdatePayload): Promise<AllocationPlan> {
  const { data } = await apiClient.patch<AllocationPlan>('/planning/plan', payload)
  return data
}

export async function getAllocationStatus(date?: string): Promise<AllocationStatus> {
  const { data } = await apiClient.get<AllocationStatus>('/planning/allocation-status', {
    params: { date },
  })
  return data
}

export async function getSurvivalBudget(date?: string): Promise<SurvivalBudget> {
  const { data } = await apiClient.get<SurvivalBudget>('/planning/survival-budget', {
    params: { date },
  })
  return data
}

export async function simulate(payload: SimulationRequest): Promise<SimulationResponse> {
  const { data } = await apiClient.post<SimulationResponse>('/planning/simulate', payload)
  return data
}
