import { useQueries } from '@tanstack/react-query'
import * as planningApi from '@/api/planning'
import { addMonths } from '@/lib/dates'
import { toISODate } from '@/lib/format'

/**
 * Allocation status for `month` and the `count` months before it. Periods
 * are calendar months on the backend, so any day inside one selects it;
 * the first of the month is used for a stable cache key shared with
 * useAllocationStatus.
 */
export function useAllocationHistory(month: Date, count: number) {
  const months = Array.from({ length: count + 1 }, (_, i) => addMonths(month, -i))
  const results = useQueries({
    queries: months.map((m) => {
      const date = toISODate(m)
      return {
        queryKey: ['planning', 'allocation-status', date],
        queryFn: () => planningApi.getAllocationStatus(date),
      }
    }),
  })
  return months.map((m, i) => ({ month: m, query: results[i] }))
}
