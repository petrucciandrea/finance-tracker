import { useQuery } from '@tanstack/react-query'
import { getPublicConfig } from '@/api/auth'

/**
 * Server-side switches the auth screens depend on. Fixed for the life of a deploy,
 * so it is fetched once. Until it is known nothing that might be a dead end
 * (sign-up, "forgot password") is offered.
 */
export function usePublicConfig() {
  const { data, isLoading } = useQuery({
    queryKey: ['public-config'],
    queryFn: getPublicConfig,
    staleTime: Infinity,
    retry: 1,
  })
  return {
    isLoading,
    registrationOpen: !!data && data.registration_mode !== 'closed',
    registrationClosed: data?.registration_mode === 'closed',
    emailEnabled: !!data?.email_enabled,
  }
}
