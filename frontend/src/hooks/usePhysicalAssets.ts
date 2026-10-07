import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as physicalAssetsApi from '@/api/physicalAssets'
import { PLANNING_KEY } from '@/hooks/usePlanning'
import { invalidatePortfolio } from '@/hooks/usePortfolio'
import { TRANSACTIONS_KEY } from '@/hooks/useTransactions'
import type {
  PhysicalAssetCreatePayload,
  PhysicalAssetSellPayload,
  PhysicalAssetUpdatePayload,
  PhysicalAssetValuationPayload,
} from '@/types'

const PHYSICAL_ASSETS_KEY = ['physical-assets'] as const

export function usePhysicalAssets(includeSold: boolean) {
  return useQuery({
    queryKey: [...PHYSICAL_ASSETS_KEY, includeSold],
    queryFn: () => physicalAssetsApi.listPhysicalAssets(includeSold),
  })
}

/**
 * Every write can move net worth and its history; one that pays from or
 * into an account also moves cash, the transactions list and the runway.
 * Invalidating all of them on every write is simpler than tracking which
 * payload carried an account.
 */
function useInvalidate() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: PHYSICAL_ASSETS_KEY })
    invalidatePortfolio(queryClient)
    queryClient.invalidateQueries({ queryKey: TRANSACTIONS_KEY })
    queryClient.invalidateQueries({ queryKey: PLANNING_KEY })
  }
}

export function useCreatePhysicalAsset() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: (payload: PhysicalAssetCreatePayload) => physicalAssetsApi.createPhysicalAsset(payload),
    onSuccess,
  })
}

export function useUpdatePhysicalAsset() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: PhysicalAssetUpdatePayload }) =>
      physicalAssetsApi.updatePhysicalAsset(id, payload),
    onSuccess,
  })
}

export function useDeletePhysicalAsset() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (id: string) => physicalAssetsApi.deletePhysicalAsset(id), onSuccess })
}

export function useSellPhysicalAsset() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: PhysicalAssetSellPayload }) =>
      physicalAssetsApi.sellPhysicalAsset(id, payload),
    onSuccess,
  })
}

export function useUnsellPhysicalAsset() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (id: string) => physicalAssetsApi.unsellPhysicalAsset(id), onSuccess })
}

export function useCreateValuation() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: PhysicalAssetValuationPayload }) =>
      physicalAssetsApi.createValuation(id, payload),
    onSuccess,
  })
}

export function useDeleteValuation() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, valuationId }: { id: string; valuationId: string }) =>
      physicalAssetsApi.deleteValuation(id, valuationId),
    onSuccess,
  })
}
