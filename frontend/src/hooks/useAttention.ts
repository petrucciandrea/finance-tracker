import { useQueries } from '@tanstack/react-query'
import * as transactionsApi from '@/api/transactions'
import { useCategories } from '@/hooks/useCategories'
import { TRANSACTIONS_KEY } from '@/hooks/useTransactions'
import { isMiscCategory, unclassifiedExpenseCategories } from '@/lib/categories'

/**
 * Counts behind the amber nav badges. Both come from data the app already
 * loads: transactions sitting in the "Varie" fallback (one count-only query
 * per Varie category, page_size 1, reading meta.total_items) and expense
 * categories with no necessity level of their own or inherited.
 */
export function useAttentionCounts() {
  const { data: categories } = useCategories()
  const miscIds = (categories ?? []).filter(isMiscCategory).map((c) => c.id)

  const miscCounts = useQueries({
    queries: miscIds.map((categoryId) => {
      const params = { category_id: categoryId, page_size: 1 }
      return {
        queryKey: [...TRANSACTIONS_KEY, 'list', params],
        queryFn: () => transactionsApi.listTransactions(params),
      }
    }),
  })

  return {
    toAssign: miscCounts.reduce((sum, q) => sum + (q.data?.meta.total_items ?? 0), 0),
    toClassify: unclassifiedExpenseCategories(categories).length,
    miscCategoryIds: miscIds,
  }
}
