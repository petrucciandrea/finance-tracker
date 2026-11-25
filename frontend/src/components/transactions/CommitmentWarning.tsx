import { Notice } from '@/components/ui/EmptyState'
import { useAlerts } from '@/hooks/useAlerts'
import { formatFullDate, formatMoney, toNumber } from '@/lib/format'

/**
 * Shown while typing a movement that would take an account below what's
 * due from it (scheduled F24s, vehicle deadlines) plus the margin — the
 * moment the threshold is reached, before the banner would say so. It
 * warns, it doesn't block: moving the money may be exactly the plan.
 */
export function CommitmentWarning({ accountId, outflow, currency }: { accountId: string; outflow: number; currency: string }) {
  const { data } = useAlerts()
  const commitment = data?.commitments.find((c) => c.account_id === accountId)
  if (!commitment || !(outflow > 0) || currency.toUpperCase() !== commitment.currency) return null

  const after = toNumber(commitment.balance) - outflow
  if (after >= toNumber(commitment.threshold)) return null
  const first = commitment.items[0]
  const money = (value: string | number) => formatMoney(value, commitment.currency)
  const due = `${money(commitment.committed)} in uscita, il primo il ${formatFullDate(first.due_date)}: ${first.label}`

  return (
    <Notice>
      {after < toNumber(commitment.committed)
        ? `Dopo questo movimento su ${commitment.account_name} resterebbero ${money(after)}: non bastano per gli addebiti programmati (${due}).`
        : `Dopo questo movimento su ${commitment.account_name} restano ${money(after)}, appena sopra gli addebiti programmati (${due}). Meglio lasciare almeno ${money(commitment.threshold)} sul conto.`}
    </Notice>
  )
}
