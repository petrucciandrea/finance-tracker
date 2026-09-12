import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as accountsApi from '@/api/accounts'
import { NET_WORTH_KEY } from '@/hooks/usePortfolio'
import type { AccountCreatePayload } from '@/types'

const ACCOUNTS_KEY = ['accounts'] as const

export function useAccounts() {
  return useQuery({
    queryKey: ACCOUNTS_KEY,
    queryFn: accountsApi.listAccounts,
  })
}

export function useCreateAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AccountCreatePayload) => accountsApi.createAccount(payload),
    onSuccess: () => {
      // Simplest correct approach for this app's size: refetch the list
      // rather than hand-merging the new item into the cache.
      queryClient.invalidateQueries({ queryKey: ACCOUNTS_KEY })
      // Net worth's per-account breakdown depends on the account list too.
      queryClient.invalidateQueries({ queryKey: NET_WORTH_KEY })
    },
  })
}

export function useDeleteAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => accountsApi.deleteAccount(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ACCOUNTS_KEY })
      // A deleted account's balance must drop out of net worth immediately,
      // not linger for up to the global 30s staleTime.
      queryClient.invalidateQueries({ queryKey: NET_WORTH_KEY })
    },
  })
}
