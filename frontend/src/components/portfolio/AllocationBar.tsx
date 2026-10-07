import { ALLOCATION_SERIES } from '@/lib/portfolio'
import { formatAmount, formatPercent } from '@/lib/format'

/**
 * Stacked share bar with a legend that always names each segment and its
 * weight — identity never rests on colour alone, and the grey cash slot
 * (deliberately neutral) is readable through its label.
 */
export function AllocationBar({ values, currency }: { values: Partial<Record<string, number>>; currency: string }) {
  const total = Object.values(values).reduce<number>((sum, v) => sum + Math.max(v ?? 0, 0), 0)
  const series = ALLOCATION_SERIES.filter((s) => (values[s.key] ?? 0) > 0)
  if (!total) return null
  return (
    <div>
      <div className="flex h-2.5 gap-0.5" aria-hidden="true">
        {series.map((s) => (
          <span key={s.key} className="block h-full rounded-[3px]" style={{ background: s.color, flex: `${values[s.key]} 1 0` }} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2 tabular-nums">
        {series.map((s) => (
          <li key={s.key} className="inline-flex items-center gap-1.5" title={`${formatAmount(values[s.key], currency)} ${currency}`}>
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
            {s.label} <b className="text-ink">{formatPercent(((values[s.key] ?? 0) / total) * 100)}</b>
          </li>
        ))}
      </ul>
    </div>
  )
}
