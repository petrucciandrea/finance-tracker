import { useState } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { AssetTransactionForm } from '@/components/portfolio/AssetTransactionForm'
import { AssetTransactionImport } from '@/components/portfolio/AssetTransactionImport'
import { HoldingsTable } from '@/components/portfolio/HoldingsTable'
import { PnlByAssetChart } from '@/components/portfolio/PnlByAssetChart'
import { PortfolioValueChart } from '@/components/portfolio/PortfolioValueChart'
import { useHoldings, useNetWorth } from '@/hooks/usePortfolio'

type PanelMode = 'none' | 'form' | 'import'

const ALLOCATION_COLORS = [
  '#1e293b', // slate-800 (cash)
  '#059669',
  '#0ea5e9',
  '#d97706',
  '#7c3aed',
  '#db2777',
  '#65a30d',
]

function formatCurrency(amount: string, currency: string): string {
  return Number(amount).toLocaleString('it-IT', { style: 'currency', currency })
}

export function PortfolioPage() {
  const { data: holdings, isLoading, isError } = useHoldings()
  const { data: netWorth } = useNetWorth()
  const [panel, setPanel] = useState<PanelMode>('none')

  function togglePanel(mode: PanelMode) {
    setPanel((current) => (current === mode ? 'none' : mode))
  }

  const allocationData = netWorth
    ? [
        { name: 'Liquidità', value: Number(netWorth.total_cash_balance) },
        ...(netWorth.holdings ?? []).map((h) => ({
          name: h.asset.symbol,
          value: Number(h.market_value_base_currency),
        })),
      ].filter((slice) => slice.value > 0)
    : []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Portfolio</h1>
        <div className="flex gap-2">
          <button
            onClick={() => togglePanel('import')}
            className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            {panel === 'import' ? 'Annulla' : 'Importa CSV'}
          </button>
          <button
            onClick={() => togglePanel('form')}
            className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            {panel === 'form' ? 'Annulla' : 'Nuova transazione'}
          </button>
        </div>
      </div>

      {netWorth && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg bg-white p-6 shadow-sm">
            <p className="text-xs font-medium uppercase text-slate-400">Patrimonio netto</p>
            <p className="mt-1 text-2xl font-semibold text-slate-800">
              {formatCurrency(netWorth.total_net_worth, netWorth.base_currency)}
            </p>
          </div>
          <div className="rounded-lg bg-white p-6 shadow-sm">
            <p className="text-xs font-medium uppercase text-slate-400">Liquidità</p>
            <p className="mt-1 text-2xl font-semibold text-slate-800">
              {formatCurrency(netWorth.total_cash_balance, netWorth.base_currency)}
            </p>
          </div>
          <div className="rounded-lg bg-white p-6 shadow-sm">
            <p className="text-xs font-medium uppercase text-slate-400">Investimenti</p>
            <p className="mt-1 text-2xl font-semibold text-slate-800">
              {formatCurrency(netWorth.total_holdings_value, netWorth.base_currency)}
            </p>
          </div>
        </div>
      )}

      {panel === 'form' && <AssetTransactionForm onDone={() => setPanel('none')} />}
      {panel === 'import' && <AssetTransactionImport onDone={() => setPanel('none')} />}

      {netWorth && <PortfolioValueChart baseCurrency={netWorth.base_currency} />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {allocationData.length > 0 && (
          <div className="rounded-lg bg-white p-6 shadow-sm">
            <p className="mb-4 text-sm font-medium text-slate-700">Allocazione</p>
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={allocationData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={50}
                    outerRadius={80}
                    // A single slice covering 100% renders as a broken sliver
                    // with a non-zero paddingAngle (Recharts subtracts the gap
                    // from the one slice it has nothing to pad against) — only
                    // pad when there's more than one slice to actually gap.
                    paddingAngle={allocationData.length > 1 ? 2 : 0}
                    // The mount-in sweep animation can get interrupted by a
                    // refetch re-rendering the chart moments later (holdings
                    // and net worth both refetch right after a mutation),
                    // leaving the arc frozen mid-sweep or blank — this is a
                    // decorative summary chart, not worth the animation risk.
                    isAnimationActive={false}
                  >
                    {allocationData.map((slice, index) => (
                      <Cell key={slice.name} fill={ALLOCATION_COLORS[index % ALLOCATION_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value) =>
                      netWorth ? formatCurrency(String(value), netWorth.base_currency) : value
                    }
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        <PnlByAssetChart holdings={holdings ?? []} />
      </div>

      {isLoading && <p className="text-slate-500">Caricamento...</p>}
      {isError && <p className="text-red-600">Errore nel caricamento del portfolio.</p>}
      {holdings && <HoldingsTable holdings={holdings} />}
    </div>
  )
}
