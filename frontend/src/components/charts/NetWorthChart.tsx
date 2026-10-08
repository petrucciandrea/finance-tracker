import { useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card } from '@/components/ui/Card'
import { Delta } from '@/components/ui/Amount'
import { EmptyState, LoadingBlock } from '@/components/ui/EmptyState'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { usePortfolioHistory } from '@/hooks/usePortfolio'
import { formatAmount, formatCompact, formatFullDate, formatShortDate } from '@/lib/format'
import { PERIOD_OPTIONS } from '@/lib/portfolio'
import type { PortfolioHistoryPeriod } from '@/types'

const PERIOD_PHRASE: Record<PortfolioHistoryPeriod, string> = {
  '1m': 'in 1 mese',
  '3m': 'in 3 mesi',
  '6m': 'in 6 mesi',
  '1y': 'in 12 mesi',
  all: 'dall’inizio',
}

interface Point {
  date: string
  value: number
  change: number | null
}

const AXIS_TICK = { fontSize: 12, fill: 'var(--color-ink-3)' }

function ChartTooltip({ active, payload, currency }: { active?: boolean; payload?: { payload: Point }[]; currency: string }) {
  if (!active || !payload?.length) return null
  const point = payload[0].payload
  return (
    <div className="rounded-[10px] border border-line bg-card px-3 py-2 text-[12px] tabular-nums shadow-[0_4px_14px_rgba(0,0,0,0.10)]">
      <div className="font-semibold text-ink-3">{formatFullDate(point.date)}</div>
      <div className="text-[14px] font-extrabold text-ink">
        {formatAmount(point.value, currency)} <span className="ccy">{currency}</span>
      </div>
      {point.change !== null && <Delta value={point.change} currency={currency} className="text-[12px]" />}
    </div>
  )
}

/** Net worth over time: one series, so no legend box — the title names it. */
export function NetWorthChart({ baseCurrency }: { baseCurrency: string }) {
  const [period, setPeriod] = useState<PortfolioHistoryPeriod>('1y')
  const { data, isLoading } = usePortfolioHistory(period)

  const points: Point[] = (data?.points ?? []).map((p, i, all) => ({
    date: p.date,
    value: Number(p.total_net_worth),
    change: i > 0 ? Number(p.total_net_worth) - Number(all[i - 1].total_net_worth) : null,
  }))
  const values = points.map((p) => p.value)
  const first = points[0]?.value ?? 0
  const last = points[points.length - 1]?.value ?? 0
  const change = last - first
  const changePct = first ? (change / Math.abs(first)) * 100 : null

  return (
    <Card
      title="Patrimonio nel tempo"
      action={<SegmentedControl label="Periodo" options={PERIOD_OPTIONS} value={period} onChange={setPeriod} size="sm" />}
    >
      {points.length > 1 && (
        <p className="mt-2 text-[12px] text-ink-2 tabular-nums">
          Min {formatAmount(Math.min(...values), baseCurrency, { digits: 0 })} · Max{' '}
          {formatAmount(Math.max(...values), baseCurrency, { digits: 0 })} {baseCurrency} ·{' '}
          <Delta value={change} percent={changePct} /> {PERIOD_PHRASE[period]}
        </p>
      )}
      <div className="mt-3 h-[240px]">
        {isLoading ? (
          <LoadingBlock className="h-full" />
        ) : points.length < 2 ? (
          <EmptyState title="Ancora pochi dati">Il grafico compare quando ci sono almeno due giorni di storico.</EmptyState>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={points}
              margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
              accessibilityLayer
              aria-label={`Patrimonio netto da ${formatAmount(first, baseCurrency)} a ${formatAmount(last, baseCurrency)} ${baseCurrency}`}
            >
              <CartesianGrid vertical={false} stroke="var(--color-line)" />
              <XAxis
                dataKey="date"
                tick={AXIS_TICK}
                tickLine={false}
                axisLine={false}
                tickFormatter={(d: string) => formatShortDate(d)}
                minTickGap={36}
              />
              <YAxis
                tick={AXIS_TICK}
                tickLine={false}
                axisLine={false}
                width={44}
                domain={['auto', 'auto']}
                tickFormatter={(v: number) => formatCompact(v)}
              />
              <Tooltip
                content={<ChartTooltip currency={baseCurrency} />}
                cursor={{ stroke: 'var(--color-ink-3)', strokeDasharray: '3 3' }}
              />
              <Area
                type="monotone"
                dataKey="value"
                name="Patrimonio netto"
                stroke="var(--color-accent)"
                strokeWidth={2}
                fill="var(--color-accent)"
                fillOpacity={0.1}
                activeDot={{ r: 5, stroke: 'var(--color-card)', strokeWidth: 3, fill: 'var(--color-accent)' }}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  )
}
