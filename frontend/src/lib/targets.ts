/**
 * Moving one target slider rebalances the others so the mix stays at 100%:
 * the unlocked ones absorb the change in proportion to their current
 * weight (60/40 → equity to 70 gives 30, not an equal split). Locked
 * buckets don't move, and the moved one can't go past what they leave.
 *
 * Only once the mix adds up to 100. While it is being built from nothing a
 * slider just sets its own value (up to what's left): spreading the rest
 * evenly would put 7% in crypto the moment equity is set to 60.
 */
export type TargetMix = Record<string, number>

const round1 = (v: number) => Math.round(v * 10) / 10

export function sumOf(mix: TargetMix): number {
  return round1(Object.values(mix).reduce((s, v) => s + v, 0))
}

export function rebalance(mix: TargetMix, changed: string, next: number, locked: ReadonlySet<string>): TargetMix {
  const buckets = Object.keys(mix)
  const lockedSum = buckets.filter((b) => b !== changed && locked.has(b)).reduce((s, b) => s + mix[b], 0)
  const free = buckets.filter((b) => b !== changed && !locked.has(b))
  const freeSum = free.reduce((s, b) => s + mix[b], 0)
  const complete = Math.abs(sumOf(mix) - 100) < 0.05

  if (!complete || freeSum === 0) {
    const room = 100 - lockedSum - freeSum
    return { ...mix, [changed]: round1(Math.min(Math.max(next, 0), room)) }
  }

  const value = round1(Math.min(Math.max(next, 0), 100 - lockedSum))
  const result: TargetMix = { ...mix, [changed]: value }
  const remaining = Math.max(0, 100 - lockedSum - value)
  for (const b of free) result[b] = round1((mix[b] * remaining) / freeSum)
  // Rounding to a tenth can leave the total a tenth off: the largest free
  // bucket takes the difference, where it is least visible.
  const drift = round1(100 - sumOf(result))
  if (drift !== 0) {
    const largest = free.reduce((a, b) => (result[b] > result[a] ? b : a))
    result[largest] = round1(Math.max(0, result[largest] + drift))
  }
  return result
}
