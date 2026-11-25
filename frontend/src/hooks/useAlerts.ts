import { useQuery } from '@tanstack/react-query'
import * as alertsApi from '@/api/alerts'
import { NET_WORTH_KEY } from '@/hooks/usePortfolio'

/**
 * Under the net-worth key on purpose: every write that moves a balance or a
 * tax figure already invalidates it (transactions, accounts, Fatture, Beni),
 * and the alerts are computed from exactly those — so they refresh with no
 * extra wiring. Vehicle deadlines invalidate it explicitly.
 */
export const ALERTS_KEY = [...NET_WORTH_KEY, 'alerts'] as const

export function useAlerts() {
  return useQuery({ queryKey: ALERTS_KEY, queryFn: alertsApi.getAlerts })
}
