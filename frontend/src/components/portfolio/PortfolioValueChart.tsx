import { useState } from 'react'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { usePortfolioHistory } from '@/hooks/usePortfolio'
import type { PortfolioHistoryPeriod } from '@/types'

const PERIOD_LABELS: Record<PortfolioHistoryPeriod, string> = {
  '1m': '1M',
  '3m': '3M',
  '6m': '6M',
  '1y': '1A',
  all: 'Tutto',
}

function formatCurrency(amount: number, currency: string): string {
  return amount.toLocaleString('it-IT', { style: 'currency', currency, maximumFractionDigits: 0 })
}

export function PortfolioValueChart({ baseCurrency }: { baseCurrency: string }) {
  const [period, setPeriod] = useState<PortfolioHistoryPeriod>('6m')
  const { data, isLoading } = usePortfolioHistory(period)

  const chartData =
    data?.points.map((p) => ({
      date: p.date,
      netWorth: Number(p.total_net_worth),
      holdings: Number(p.total_holdings_value_base_currency),
    })) ?? []

  return (
    <div className="rounded-lg bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-medium text-slate-700">Andamento del portafoglio</p>
        <div className="flex gap-1">
          {(Object.keys(PERIOD_LABELS) as PortfolioHistoryPeriod[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`rounded px-2 py-1 text-xs font-medium ${
                period === p ? 'bg-slate-800 text-white' : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </div>

      <div className="h-64 w-full">
        {isLoading && <p className="text-sm text-slate-500">Caricamento...</p>}
        {!isLoading && chartData.length === 0 && (
          <p className="text-sm text-slate-500">Nessun dato per questo periodo.</p>
        )}
        {!isLoading && chartData.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="netWorthFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#059669" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#059669" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                tickFormatter={(d: string) => d.slice(5)}
                minTickGap={30}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                tickFormatter={(v: number) => formatCurrency(v, baseCurrency)}
                width={70}
              />
              <Tooltip formatter={(value) => formatCurrency(Number(value), baseCurrency)} />
              <Area
                type="monotone"
                dataKey="netWorth"
                name="Patrimonio netto"
                stroke="#059669"
                fill="url(#netWorthFill)"
                strokeWidth={2}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
