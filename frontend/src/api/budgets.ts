import { apiClient } from './client'
import type { Budget, BudgetCreatePayload, BudgetStatus, BudgetUpdatePayload } from '@/types'

export async function listBudgets(): Promise<Budget[]> {
  const { data } = await apiClient.get<Budget[]>('/budgets')
  return data
}

export async function getBudget(id: string): Promise<Budget> {
  const { data } = await apiClient.get<Budget>(`/budgets/${id}`)
  return data
}

export async function createBudget(payload: BudgetCreatePayload): Promise<Budget> {
  const { data } = await apiClient.post<Budget>('/budgets', payload)
  return data
}

export async function updateBudget(id: string, payload: BudgetUpdatePayload): Promise<Budget> {
  const { data } = await apiClient.patch<Budget>(`/budgets/${id}`, payload)
  return data
}

export async function deleteBudget(id: string): Promise<void> {
  await apiClient.delete(`/budgets/${id}`)
}

export async function getBudgetsStatus(date?: string): Promise<BudgetStatus[]> {
  const { data } = await apiClient.get<BudgetStatus[]>('/budgets/status', { params: { date } })
  return data
}
