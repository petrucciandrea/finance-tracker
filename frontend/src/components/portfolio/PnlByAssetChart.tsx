import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { HoldingWithValue } from '@/types'

function formatCurrency(amount: number): string {
  return amount.toLocaleString('it-IT', { maximumFractionDigits: 0 })
}

export function PnlByAssetChart({ holdings }: { holdings: HoldingWithValue[] }) {
  const data = holdings.map((h) => ({
    symbol: h.asset.symbol,
    unrealized: Number(h.unrealized_pnl),
    realized: Number(h.realized_pnl),
  }))

  if (data.length === 0) {
    return (
      <div className="rounded-lg bg-white p-6 shadow-sm">
        <p className="mb-4 text-sm font-medium text-slate-700">Guadagno/perdita per asset</p>
        <p className="text-sm text-slate-500">Nessuna posizione ancora.</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg bg-white p-6 shadow-sm">
      <p className="mb-4 text-sm font-medium text-slate-700">Guadagno/perdita per asset</p>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="symbol" tick={{ fontSize: 11, fill: '#94a3b8' }} />
            <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickFormatter={formatCurrency} width={60} />
            <Tooltip formatter={(value) => formatCurrency(Number(value))} />
            <Bar dataKey="unrealized" name="Non realizzato" isAnimationActive={false}>
              {data.map((entry) => (
                <Cell key={entry.symbol} fill={entry.unrealized >= 0 ? '#059669' : '#dc2626'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
