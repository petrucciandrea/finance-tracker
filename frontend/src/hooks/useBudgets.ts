import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as budgetsApi from '@/api/budgets'
import type { BudgetCreatePayload, BudgetUpdatePayload } from '@/types'

const BUDGETS_KEY = ['budgets'] as const
// Exported so useTransactions.ts can invalidate it too — budget spend is
// derived from transactions, so a transaction mutation must bust this cache
// even though it lives outside the 'transactions' query key namespace.
export const BUDGETS_STATUS_KEY = ['budgets', 'status'] as const

export function useBudgets() {
  return useQuery({
    queryKey: BUDGETS_KEY,
    queryFn: budgetsApi.listBudgets,
  })
}

export function useBudgetsStatus(date?: string) {
  return useQuery({
    queryKey: [...BUDGETS_STATUS_KEY, date],
    queryFn: () => budgetsApi.getBudgetsStatus(date),
  })
}

function invalidateBudgets(queryClient: ReturnType<typeof useQueryClient>) {
  // Status depends on the budgets list (and on category names) — invalidate
  // both together rather than trying to patch either cache by hand.
  queryClient.invalidateQueries({ queryKey: BUDGETS_KEY })
  queryClient.invalidateQueries({ queryKey: BUDGETS_STATUS_KEY })
}

export function useCreateBudget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: BudgetCreatePayload) => budgetsApi.createBudget(payload),
    onSuccess: () => invalidateBudgets(queryClient),
  })
}

export function useUpdateBudget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: BudgetUpdatePayload }) =>
      budgetsApi.updateBudget(id, payload),
    onSuccess: () => invalidateBudgets(queryClient),
  })
}

export function useDeleteBudget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => budgetsApi.deleteBudget(id),
    onSuccess: () => invalidateBudgets(queryClient),
  })
}
