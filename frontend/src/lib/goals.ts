import type { Account, SavingsGoalKind, SavingsGoalSource } from '@/types'

// The pillar each kind of goal belongs to (see PillarsSection).
export const KIND_LABELS: Record<SavingsGoalKind, string> = {
  emergency_fund: 'Fondo emergenza',
  medium_term: 'Accantonamento',
  long_term: 'Investimento',
}

// The plan's pillars, in the order money fills them (the tax provision
// comes before all of them, as a debt). Goals only live in 2–4.
export const PILLAR_TITLES = {
  operating: 'Liquidità',
  emergency: 'Fondo emergenza',
  planned: 'Accantonamenti',
  investing: 'Investimenti',
} as const

export const PILLAR_OF_KIND: Record<SavingsGoalKind, { number: number; title: string }> = {
  emergency_fund: { number: 2, title: PILLAR_TITLES.emergency },
  medium_term: { number: 3, title: PILLAR_TITLES.planned },
  long_term: { number: 4, title: PILLAR_TITLES.investing },
}

export function sourceLabel(source: SavingsGoalSource, accounts: Account[] | undefined): string {
  const account = accounts?.find((a) => a.id === source.account_id)?.name ?? 'Conto eliminato'
  return source.asset ? `${source.asset.symbol} in ${account}` : account
}
