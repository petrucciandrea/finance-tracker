import { Fragment, useState } from 'react'
import { useAssetTransactionsList, useDeleteAssetTransaction } from '@/hooks/useAssetTransactions'
import type { AssetType, HoldingWithValue } from '@/types'

const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  stock: 'Azione',
  etf: 'ETF',
  crypto: 'Crypto',
}

function formatCurrency(amount: string, currency: string): string {
  return Number(amount).toLocaleString('it-IT', { style: 'currency', currency })
}

function HoldingHistoryRow({ holding }: { holding: HoldingWithValue }) {
  const { data: transactions, isLoading } = useAssetTransactionsList({
    account_id: holding.account_id,
    asset_id: holding.asset.id,
  })
  const deleteAssetTransaction = useDeleteAssetTransaction()

  async function handleDelete(id: string) {
    if (!window.confirm('Eliminare questa transazione?')) return
    await deleteAssetTransaction.mutateAsync(id)
  }

  return (
    <tr>
      <td colSpan={8} className="bg-slate-50 px-4 py-3">
        {isLoading && <p className="text-sm text-slate-500">Caricamento storico...</p>}
        {transactions && transactions.length === 0 && (
          <p className="text-sm text-slate-500">Nessuna transazione.</p>
        )}
        {transactions && transactions.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium uppercase text-slate-400">
                <th className="py-1 pr-3">Data</th>
                <th className="py-1 pr-3">Operazione</th>
                <th className="py-1 pr-3">Quantità</th>
                <th className="py-1 pr-3">Prezzo</th>
                <th className="py-1 pr-3">Commissioni</th>
                <th className="py-1 pr-3">Note</th>
                <th className="py-1 pr-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {transactions.map((tx) => (
                <tr key={tx.id}>
                  <td className="py-1.5 pr-3">{tx.date}</td>
                  <td className="py-1.5 pr-3">
                    <span
                      className={tx.type === 'buy' ? 'text-green-700' : 'text-red-700'}
                    >
                      {tx.type === 'buy' ? 'Acquisto' : 'Vendita'}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3">{tx.quantity}</td>
                  <td className="py-1.5 pr-3">{formatCurrency(tx.price, holding.asset.currency)}</td>
                  <td className="py-1.5 pr-3">{formatCurrency(tx.fee, holding.asset.currency)}</td>
                  <td className="py-1.5 pr-3 text-slate-500">{tx.notes || '—'}</td>
                  <td className="py-1.5 pr-3">
                    <button
                      onClick={() => handleDelete(tx.id)}
                      className="font-medium text-red-600 hover:underline"
                    >
                      Elimina
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </td>
    </tr>
  )
}

export function HoldingsTable({ holdings }: { holdings: HoldingWithValue[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (holdings.length === 0) {
    return (
      <div className="rounded-lg bg-white p-6 text-sm text-slate-500 shadow-sm">
        Nessuna posizione ancora. Registra una transazione per iniziare.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg bg-white shadow-sm">
      <table className="min-w-full divide-y divide-slate-100 text-sm">
        <thead>
          <tr className="text-left text-xs font-medium uppercase text-slate-400">
            <th className="px-4 py-3">Asset</th>
            <th className="px-4 py-3">Tipo</th>
            <th className="px-4 py-3">Quantità</th>
            <th className="px-4 py-3">Prezzo medio</th>
            <th className="px-4 py-3">Prezzo attuale</th>
            <th className="px-4 py-3">Valore</th>
            <th className="px-4 py-3">P&L</th>
            <th className="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {holdings.map((holding) => (
            <Fragment key={holding.id}>
              <tr
                className="cursor-pointer hover:bg-slate-50"
                onClick={() => setExpandedId((id) => (id === holding.id ? null : holding.id))}
              >
                <td className="px-4 py-3">
                  <p className="font-medium text-slate-800">{holding.asset.symbol}</p>
                  <p className="text-xs text-slate-400">{holding.asset.name}</p>
                </td>
                <td className="px-4 py-3">{ASSET_TYPE_LABELS[holding.asset.asset_type]}</td>
                <td className="px-4 py-3">{holding.quantity}</td>
                <td className="px-4 py-3">{formatCurrency(holding.avg_buy_price, holding.asset.currency)}</td>
                <td className="px-4 py-3">{formatCurrency(holding.current_price, holding.asset.currency)}</td>
                <td className="px-4 py-3">{formatCurrency(holding.market_value, holding.asset.currency)}</td>
                <td
                  className={
                    Number(holding.unrealized_pnl) < 0
                      ? 'px-4 py-3 text-red-600'
                      : 'px-4 py-3 text-green-600'
                  }
                >
                  {formatCurrency(holding.unrealized_pnl, holding.asset.currency)} (
                  {holding.unrealized_pnl_percentage}%)
                  {Number(holding.realized_pnl) !== 0 && (
                    <p className="text-xs text-slate-400">
                      Realizzato: {formatCurrency(holding.realized_pnl, holding.asset.currency)}
                    </p>
                  )}
                </td>
                <td className="px-4 py-3 text-xs font-medium text-slate-500">
                  {expandedId === holding.id ? 'Nascondi ▲' : 'Storico ▼'}
                </td>
              </tr>
              {expandedId === holding.id && <HoldingHistoryRow holding={holding} />}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
