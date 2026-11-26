import type { Account, SavingsGoalKind, SavingsGoalSource } from '@/types'

// The pillar each kind of goal belongs to (see PillarsSection).
export const KIND_LABELS: Record<SavingsGoalKind, string> = {
  emergency_fund: 'Fondo emergenza',
  medium_term: 'Accantonamento',
  long_term: 'Investimento',
}

export function sourceLabel(source: SavingsGoalSource, accounts: Account[] | undefined): string {
  const account = accounts?.find((a) => a.id === source.account_id)?.name ?? 'Conto eliminato'
  return source.asset ? `${source.asset.symbol} in ${account}` : account
}
