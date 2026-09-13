import { useQuery, useQueryClient } from '@tanstack/react-query'
import * as portfolioApi from '@/api/portfolio'
import type { AssetType, PortfolioHistoryPeriod } from '@/types'

// Exported so useAssetTransactions.ts / useTransactions.ts can invalidate
// these too — holdings and net worth are both derived from transactions
// that live outside their own query keys.
export const HOLDINGS_KEY = ['holdings'] as const
export const NET_WORTH_KEY = ['net-worth'] as const

// Prices refresh on-demand (cache-first on the backend, one external fetch
// per asset per day) — polling here just keeps the UI reasonably fresh
// while the page is open. The DB cache, not this interval, is what keeps
// this app from hammering Yahoo Finance's unofficial, unrate-limited-by-us
// endpoint on every render.
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

export function usePortfolioHistory(period: PortfolioHistoryPeriod) {
  return useQuery({
    queryKey: ['portfolio-history', period],
    queryFn: () => portfolioApi.getPortfolioHistory(period),
  })
}

export function invalidatePortfolio(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: HOLDINGS_KEY })
  queryClient.invalidateQueries({ queryKey: NET_WORTH_KEY })
  queryClient.invalidateQueries({ queryKey: ['portfolio-history'] })
}
