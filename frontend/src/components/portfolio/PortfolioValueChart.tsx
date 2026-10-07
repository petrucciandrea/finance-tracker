import { useState } from 'react'
import { Area, ComposedChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card } from '@/components/ui/Card'
import { EmptyState, LoadingBlock } from '@/components/ui/EmptyState'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAssetTransactionsList } from '@/hooks/useAssetTransactions'
import { usePortfolioHistory } from '@/hooks/usePortfolio'
import { formatAmount, formatCompact, formatFullDate, formatShortDate } from '@/lib/format'
import { PERIOD_OPTIONS } from '@/lib/portfolio'
import type { PortfolioHistoryPeriod } from '@/types'

interface Point {
  date: string
  value: number
  invested: number
}

const AXIS_TICK = { fontSize: 12, fill: 'var(--color-ink-3)' }

function ChartTooltip({ active, payload, currency }: { active?: boolean; payload?: { payload: Point }[]; currency: string }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  const gain = p.value - p.invested
  return (
    <div className="rounded-[10px] border border-line bg-card px-3 py-2 text-[12px] tabular-nums shadow-[0_4px_14px_rgba(0,0,0,0.10)]">
      <div className="font-semibold text-ink-3">{formatFullDate(p.date)}</div>
      <div className="mt-1 flex justify-between gap-4">
        <span className="text-ink-2">Valore</span>
        <b>
          {formatAmount(p.value, currency)} <span className="ccy">{currency}</span>
        </b>
      </div>
      <div className="flex justify-between gap-4">
        <span className="text-ink-2">Capitale investito</span>
        <b>
          {formatAmount(p.invested, currency)} <span className="ccy">{currency}</span>
        </b>
      </div>
      <div className={`mt-0.5 font-extrabold ${gain >= 0 ? 'text-pos' : 'text-neg'}`}>
        {gain >= 0 ? '▲' : '▼'} {formatAmount(gain, currency, { sign: 'always' })} non realizzato
      </div>
    </div>
  )
}

/**
 * Market value of the positions against net invested capital, both in the
 * base currency on one axis. Invested capital is cumulative buys minus
 * sells (amount_base_currency at each trade's own rate), so the gap
 * between the lines is the gain — no second scale needed.
 */
export function PortfolioValueChart({ baseCurrency }: { baseCurrency: string }) {
  const [period, setPeriod] = useState<PortfolioHistoryPeriod>('6m')
  const { data, isLoading } = usePortfolioHistory(period)
  const { data: trades } = useAssetTransactionsList()

  const sortedTrades = [...(trades ?? [])].filter((t) => !t.deleted_at).sort((a, b) => a.date.localeCompare(b.date))
  const points: Point[] = (data?.points ?? []).map((p) => {
    let invested = 0
    for (const t of sortedTrades) {
      if (t.date > p.date) break
      invested += (t.type === 'buy' ? 1 : -1) * Number(t.amount_base_currency)
    }
    return { date: p.date, value: Number(p.total_holdings_value_base_currency), invested }
  })

  return (
    <Card
      title="Valore e capitale investito"
      className="flex-[999_1_560px]"
      action={<SegmentedControl label="Periodo" options={PERIOD_OPTIONS} value={period} onChange={setPeriod} size="sm" />}
    >
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-ink-2">
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="h-0.5 w-3.5 bg-accent" />
          Valore di mercato
        </li>
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="w-3.5 border-t-2 border-dashed border-ink-3" />
          Capitale investito (acquisti − vendite, al cambio del giorno)
        </li>
      </ul>
      <div className="mt-3 h-[240px]">
        {isLoading ? (
          <LoadingBlock className="h-full" />
        ) : points.length < 2 ? (
          <EmptyState title="Ancora pochi dati">Il grafico compare dopo almeno due giorni di storico.</EmptyState>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} accessibilityLayer>
              <CartesianGrid vertical={false} stroke="var(--color-line)" />
              <XAxis dataKey="date" tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={(d: string) => formatShortDate(d)} minTickGap={36} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={44} tickFormatter={(v: number) => formatCompact(v)} />
              <Tooltip content={<ChartTooltip currency={baseCurrency} />} cursor={{ stroke: 'var(--color-ink-3)', strokeDasharray: '3 3' }} />
              <Area
                type="monotone"
                dataKey="value"
                name="Valore di mercato"
                stroke="var(--color-accent)"
                strokeWidth={2}
                fill="var(--color-accent)"
                fillOpacity={0.1}
                isAnimationActive={false}
                activeDot={{ r: 5, stroke: 'var(--color-card)', strokeWidth: 3, fill: 'var(--color-accent)' }}
              />
              <Line
                type="stepAfter"
                dataKey="invested"
                name="Capitale investito"
                stroke="var(--color-ink-3)"
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  )
}
