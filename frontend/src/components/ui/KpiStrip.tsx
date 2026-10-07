import type { ReactNode } from 'react'

export interface Kpi {
  label: string
  value: ReactNode
  sub?: ReactNode
  // Colour of the value: 'pos' for incomes and gains only.
  tone?: 'default' | 'pos' | 'neg'
  subTone?: 'muted' | 'pos' | 'neg' | 'warn'
}

const TONES = { default: 'text-ink', pos: 'text-pos', neg: 'text-neg' }
const SUB_TONES = { muted: 'text-ink-3', pos: 'text-pos', neg: 'text-neg', warn: 'text-warn' }

/**
 * A row of indicators separated by hairlines; the first one is the headline
 * (bigger, on accent-soft). Wraps with auto-fit, and the box-shadow
 * dividers draw correctly on whichever cell starts a new row.
 */
export function KpiStrip({ items, label, min = 165 }: { items: Kpi[]; label: string; min?: number }) {
  return (
    <section
      aria-label={label}
      className="grid overflow-hidden rounded-[14px] border border-line bg-card"
      style={{ gridTemplateColumns: `repeat(auto-fit, minmax(min(${min}px, 100%), 1fr))` }}
    >
      {items.map((kpi, i) => (
        <div
          key={kpi.label}
          className={`px-4 py-3.5 shadow-[-1px_0_0_var(--color-line),0_-1px_0_var(--color-line)] sm:px-[18px] ${i === 0 ? 'bg-accent-soft' : ''}`}
        >
          <div className="text-[12px] font-bold text-ink-3">{kpi.label}</div>
          <div
            className={`mt-0.5 font-extrabold tracking-[-0.02em] tabular-nums ${i === 0 ? 'text-[26px]' : 'text-[20px]'} ${TONES[kpi.tone ?? 'default']}`}
          >
            {kpi.value}
          </div>
          {kpi.sub && (
            <div className={`mt-0.5 text-[12px] font-semibold tabular-nums ${SUB_TONES[kpi.subTone ?? 'muted']}`}>
              {kpi.sub}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}
