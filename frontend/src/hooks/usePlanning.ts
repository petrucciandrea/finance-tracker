import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as planningApi from '@/api/planning'
import type { AllocationPlanUpdatePayload, SimulationRequest } from '@/types'

// Exported so useTransactions.ts and useAccounts.ts can invalidate it too —
// the allocation status, the survival budget and (from phase C) the
// waterfall are all derived from transactions and balances, but cached
// under their own top-level key.
export const PLANNING_KEY = ['planning'] as const

const PLAN_KEY = ['planning', 'plan'] as const
const ALLOCATION_STATUS_KEY = ['planning', 'allocation-status'] as const
const SURVIVAL_KEY = ['planning', 'survival-budget'] as const

export function usePlan() {
  return useQuery({ queryKey: PLAN_KEY, queryFn: planningApi.getPlan })
}

export function useAllocationStatus(date?: string) {
  return useQuery({
    queryKey: [...ALLOCATION_STATUS_KEY, date],
    queryFn: () => planningApi.getAllocationStatus(date),
  })
}

export function useSurvivalBudget(date?: string) {
  return useQuery({
    queryKey: [...SURVIVAL_KEY, date],
    queryFn: () => planningApi.getSurvivalBudget(date),
  })
}

export function useUpdatePlan() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AllocationPlanUpdatePayload) => planningApi.updatePlan(payload),
    // Changing the percentages or the lookback window moves every derived
    // figure, so bust the whole namespace rather than just the plan.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PLANNING_KEY }),
  })
}

export function useSimulate() {
  // A POST that writes nothing — deliberately no invalidation, same as the
  // CSV import preview mutations.
  return useMutation({
    mutationFn: (payload: SimulationRequest) => planningApi.simulate(payload),
  })
}
