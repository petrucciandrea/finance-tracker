import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as portfolioApi from '@/api/portfolio'
import type { AssetType, HoldingCreatePayload, HoldingUpdatePayload } from '@/types'

const HOLDINGS_KEY = ['holdings'] as const
// Exported so useTransactions.ts can invalidate it too — net worth's cash
// balance is derived from transactions, so a transaction mutation must bust
// this cache even though it lives outside the 'transactions' query key.
export const NET_WORTH_KEY = ['net-worth'] as const

// Prices refresh on-demand (cache-first on the backend, one external fetch
// per asset per day) — polling here just keeps the UI reasonably fresh
// while the page is open. The DB cache, not this interval, is what protects
// Alpha Vantage's 25-requests/day free tier.
const POLL_INTERVAL_MS = 45_000

export function useHoldings() {
  return useQuery({
    queryKey: HOLDINGS_KEY,
    queryFn: portfolioApi.listHoldings,
    refetchInterval: POLL_INTERVAL_MS,
  })
}

export function useNetWorth() {
  return useQuery({
    queryKey: NET_WORTH_KEY,
    queryFn: portfolioApi.getNetWorth,
    refetchInterval: POLL_INTERVAL_MS,
  })
}

export function useSearchAssets(q: string, assetType: AssetType) {
  return useQuery({
    queryKey: ['asset-search', assetType, q],
    queryFn: () => portfolioApi.searchAssets(q, assetType),
    enabled: q.length >= 2,
  })
}

function invalidatePortfolio(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: HOLDINGS_KEY })
  queryClient.invalidateQueries({ queryKey: NET_WORTH_KEY })
}

export function useCreateHolding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: HoldingCreatePayload) => portfolioApi.createHolding(payload),
    onSuccess: () => invalidatePortfolio(queryClient),
  })
}

export function useUpdateHolding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: HoldingUpdatePayload }) =>
      portfolioApi.updateHolding(id, payload),
    onSuccess: () => invalidatePortfolio(queryClient),
  })
}

export function useDeleteHolding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => portfolioApi.deleteHolding(id),
    onSuccess: () => invalidatePortfolio(queryClient),
  })
}
