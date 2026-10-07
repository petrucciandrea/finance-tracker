import type { StatusKind } from '@/components/ui/StatusChip'
import type { AllocationBucket, AllocationBucketStatus } from '@/types'

export const BUCKET_ORDER: AllocationBucket[] = ['primary', 'useful', 'discretionary', 'savings']

export const BUCKET_LABELS: Record<AllocationBucket, string> = {
  primary: 'Spese primarie',
  useful: 'Spese utili',
  discretionary: 'Spese accessorie',
  savings: 'Risparmio',
}

export const BUCKET_SHORT: Record<AllocationBucket, string> = {
  primary: 'Primarie',
  useful: 'Utili',
  discretionary: 'Accessorie',
  savings: 'Risparmio',
}

// Spending a little over the elapsed share of the month is noise, not a
// warning; past this margin the bar turns amber.
const PACE_TOLERANCE = 5

/**
 * Chip for one bucket in one month. Spend buckets are bad when over target
 * and "attention" when ahead of the month's pace. Savings is inverted —
 * it's the residual, so it's bad when *under* target, and only once the
 * month is closed (mid-month the residual is still moving).
 */
export function bucketStatus(
  status: AllocationBucketStatus,
  { pace, closed }: { pace: number; closed: boolean },
): { kind: StatusKind; label: string } {
  if (status.bucket === 'savings') {
    if (Number(status.target_amount) <= 0) return { kind: 'ok', label: 'Nessun target' }
    if (!status.is_over_target && status.percentage_used < 100) {
      return closed ? { kind: 'over', label: '▼ Sotto il target' } : { kind: 'warn', label: 'Sotto il target, per ora' }
    }
    return { kind: 'good', label: closed ? 'Target raggiunto ✓' : 'Residuo sopra il target ✓' }
  }
  if (status.is_over_target) return { kind: 'over', label: '▲ Fuori piano' }
  if (!closed && status.percentage_used > pace + PACE_TOLERANCE) return { kind: 'warn', label: 'Sopra il ritmo' }
  return { kind: 'ok', label: 'In linea' }
}

/** A closed month "kept the plan" on a bucket when the bucket isn't bad. */
export function bucketKept(status: AllocationBucketStatus): boolean {
  if (Number(status.target_amount) <= 0) return true
  return status.bucket === 'savings' ? status.percentage_used >= 100 : !status.is_over_target
}

export function sortBuckets(buckets: AllocationBucketStatus[]): AllocationBucketStatus[] {
  return [...buckets].sort((a, b) => BUCKET_ORDER.indexOf(a.bucket) - BUCKET_ORDER.indexOf(b.bucket))
}

/** "50 / 25 / 15 / 10" */
export function modelLabel(buckets: AllocationBucketStatus[]): string {
  return sortBuckets(buckets)
    .map((b) => Number(b.percentage).toLocaleString('it-IT', { maximumFractionDigits: 1 }))
    .join(' / ')
}
