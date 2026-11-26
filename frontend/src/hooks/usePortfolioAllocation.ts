import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as api from '@/api/portfolioAllocation'
import type { AssetExposureUpdatePayload, ExposureDimension } from '@/types'

// `invalidatePortfolio` (usePortfolio.ts) busts ALLOCATION_KEY too, so every
// write that moves holdings refreshes the composition.
const ALLOCATION_KEY = ['portfolio', 'allocation'] as const
const EXPOSURES_KEY = ['portfolio', 'exposures'] as const

export function useAllocation(dimension: ExposureDimension, includeCash: boolean) {
  return useQuery({
    queryKey: [...ALLOCATION_KEY, dimension, includeCash],
    queryFn: () => api.getAllocation(dimension, includeCash),
  })
}

export function useAssetExposures(assetId: string | null) {
  return useQuery({
    queryKey: [...EXPOSURES_KEY, assetId],
    queryFn: () => api.getExposures(assetId as string),
    enabled: !!assetId,
  })
}

function useInvalidate() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ALLOCATION_KEY })
    queryClient.invalidateQueries({ queryKey: EXPOSURES_KEY })
    // The planning rules and the alerts read the same weights.
    queryClient.invalidateQueries({ queryKey: ['planning'] })
    queryClient.invalidateQueries({ queryKey: ['net-worth'] })
  }
}

export function useSaveExposures() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ assetId, dimension, payload }: { assetId: string; dimension: ExposureDimension; payload: AssetExposureUpdatePayload }) =>
      api.putExposures(assetId, dimension, payload),
    onSuccess: invalidate,
  })
}

export function useResetExposures() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ assetId, dimension }: { assetId: string; dimension: ExposureDimension }) => api.resetExposures(assetId, dimension),
    onSuccess: invalidate,
  })
}
