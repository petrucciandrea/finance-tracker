import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { formatAmount } from '@/lib/format'
import { unrealizedPnlBase } from '@/lib/portfolio'
import type { HoldingWithValue } from '@/types'

/**
 * Diverging bars around zero: each position's unrealised gain or loss in
 * the base currency. Gains extend right in green, losses left in red, and
 * every bar carries its signed value and arrow, so colour isn't the only cue.
 */
export function PnlByAssetChart({ holdings, baseCurrency }: { holdings: HoldingWithValue[]; baseCurrency: string }) {
  const rows = holdings
    .map((h) => ({ id: h.id, symbol: h.asset.symbol, value: unrealizedPnlBase(h) }))
    .sort((a, b) => b.value - a.value)
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1)

  return (
    <Card title="Contributo al guadagno" className="flex-[1_1_380px]">
      <p className="mt-0.5 text-[12px] text-ink-3">Guadagno o perdita non realizzati per titolo, in {baseCurrency}</p>
      {rows.length === 0 ? (
        <div className="mt-3">
          <EmptyState title="Nessuna posizione" />
        </div>
      ) : (
        <ul className="mt-3 flex flex-col gap-2 tabular-nums">
          {rows.map((r) => {
            const width = `${(Math.abs(r.value) / max) * 50}%`
            const up = r.value >= 0
            return (
              <li key={r.id} className="grid grid-cols-[64px_1fr_auto] items-center gap-2 text-[13px]">
                <span className="truncate font-extrabold">{r.symbol}</span>
                <span className="relative h-3.5" aria-hidden="true">
                  <span className="absolute inset-y-[-3px] left-1/2 w-px bg-ink-3/50" />
                  <span
                    className={`absolute top-0 h-full ${up ? 'left-1/2 rounded-r-[4px] bg-pos' : 'right-1/2 rounded-l-[4px] bg-neg'}`}
                    style={{ width }}
                  />
                </span>
                <span className={`min-w-[110px] text-right font-bold ${up ? 'text-pos' : 'text-neg'}`}>
                  {up ? '▲' : '▼'} {formatAmount(r.value, baseCurrency, { sign: 'always' })}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
