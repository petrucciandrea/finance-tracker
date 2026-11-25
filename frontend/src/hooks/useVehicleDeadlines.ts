import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as deadlinesApi from '@/api/vehicleDeadlines'
import { ALERTS_KEY } from '@/hooks/useAlerts'
import type { VehicleDeadlineCompletePayload, VehicleDeadlineCreatePayload, VehicleDeadlineUpdatePayload } from '@/types'

const VEHICLE_DEADLINES_KEY = ['vehicle-deadlines'] as const

export function useVehicleDeadlines(includeDone = false) {
  return useQuery({
    queryKey: [...VEHICLE_DEADLINES_KEY, includeDone],
    queryFn: () => deadlinesApi.listVehicleDeadlines(includeDone),
  })
}

// A deadline moves no money, but it is a commitment on its account and an alert.
function useInvalidate() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: VEHICLE_DEADLINES_KEY })
    queryClient.invalidateQueries({ queryKey: ALERTS_KEY })
  }
}

export function useCreateVehicleDeadline() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (payload: VehicleDeadlineCreatePayload) => deadlinesApi.createVehicleDeadline(payload), onSuccess })
}

export function useUpdateVehicleDeadline() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: VehicleDeadlineUpdatePayload }) => deadlinesApi.updateVehicleDeadline(id, payload),
    onSuccess,
  })
}

export function useCompleteVehicleDeadline() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: VehicleDeadlineCompletePayload }) => deadlinesApi.completeVehicleDeadline(id, payload),
    onSuccess,
  })
}

export function useReopenVehicleDeadline() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (id: string) => deadlinesApi.reopenVehicleDeadline(id), onSuccess })
}

export function useDeleteVehicleDeadline() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (id: string) => deadlinesApi.deleteVehicleDeadline(id), onSuccess })
}
