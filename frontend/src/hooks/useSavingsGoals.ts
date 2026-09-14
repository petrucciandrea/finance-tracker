import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as goalsApi from '@/api/savingsGoals'
import { PLANNING_KEY } from '@/hooks/usePlanning'
import type { SavingsGoalCreatePayload, SavingsGoalUpdatePayload } from '@/types'

const GOALS_KEY = ['planning', 'goals'] as const
const WATERFALL_KEY = ['planning', 'waterfall'] as const

export function useSavingsGoals() {
  return useQuery({ queryKey: GOALS_KEY, queryFn: goalsApi.listGoals })
}

export function useWaterfall(date?: string) {
  return useQuery({
    queryKey: [...WATERFALL_KEY, date],
    queryFn: () => goalsApi.getWaterfall(date),
  })
}

// Every goal mutation moves the cascade, and the cascade also reads the
// allocation plan and the primary-expense average — so bust the whole
// planning namespace rather than trying to predict what changed.
function invalidatePlanning(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: PLANNING_KEY })
}

export function useCreateGoal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SavingsGoalCreatePayload) => goalsApi.createGoal(payload),
    onSuccess: () => invalidatePlanning(queryClient),
  })
}

export function useUpdateGoal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SavingsGoalUpdatePayload }) =>
      goalsApi.updateGoal(id, payload),
    onSuccess: () => invalidatePlanning(queryClient),
  })
}

export function useDeleteGoal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => goalsApi.deleteGoal(id),
    onSuccess: () => invalidatePlanning(queryClient),
  })
}

export function useAddGoalSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ goalId, accountId }: { goalId: string; accountId: string }) =>
      goalsApi.addSource(goalId, accountId),
    onSuccess: () => invalidatePlanning(queryClient),
  })
}

export function useRemoveGoalSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ goalId, sourceId }: { goalId: string; sourceId: string }) =>
      goalsApi.removeSource(goalId, sourceId),
    onSuccess: () => invalidatePlanning(queryClient),
  })
}
