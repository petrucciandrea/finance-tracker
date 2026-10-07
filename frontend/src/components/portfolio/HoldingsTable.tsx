import { Fragment, useState } from 'react'
import { Delta } from '@/components/ui/Amount'
import { ConfirmDialog } from '@/components/ui/Dialog'
import { EmptyState, LoadingBlock } from '@/components/ui/EmptyState'
import { ChevronDownIcon } from '@/components/ui/Icon'
import { RowMenu } from '@/components/ui/RowMenu'
import { useAccounts } from '@/hooks/useAccounts'
import { useAssetTransactionsList, useDeleteAssetTransaction } from '@/hooks/useAssetTransactions'
import { apiErrorMessage } from '@/lib/apiError'
import { indexById } from '@/lib/categories'
import { formatAmount, formatPercent, formatQuantity, formatShortDate } from '@/lib/format'
import { ASSET_TYPE_LABELS } from '@/lib/portfolio'
import type { AssetTransaction, HoldingWithValue } from '@/types'

function HoldingHistory({ holding }: { holding: HoldingWithValue }) {
  const { data: transactions, isLoading } = useAssetTransactionsList({
    account_id: holding.account_id,
    asset_id: holding.asset.id,
  })
  const deleteAssetTransaction = useDeleteAssetTransaction()
  const [deleting, setDeleting] = useState<AssetTransaction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ccy = holding.asset.currency

  async function confirmDelete() {
    if (!deleting) return
    setError(null)
    try {
      await deleteAssetTransaction.mutateAsync(deleting.id)
      setDeleting(null)
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }

  if (isLoading) return <LoadingBlock className="h-16" label="Caricamento storico…" />
  if (!transactions?.length) return <p className="text-[13px] text-ink-3">Nessuna operazione.</p>
  return (
    <>
      <ul className="flex flex-col">
        {transactions.map((tx) => (
          <li key={tx.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line py-1.5 text-[13px] first:border-t-0">
            <span className="w-14 text-ink-3">{formatShortDate(tx.date)}</span>
            <span className={`w-20 font-bold ${tx.type === 'buy' ? 'text-ink' : 'text-pos'}`}>{tx.type === 'buy' ? 'Acquisto' : 'Vendita'}</span>
            <span className="flex-1">
              {formatQuantity(tx.quantity)} × {formatAmount(tx.price, ccy)} <span className="ccy">{ccy}</span>
              {Number(tx.fee) > 0 && <span className="text-ink-3"> · comm. {formatAmount(tx.fee, ccy)}</span>}
              {tx.notes && <span className="text-ink-3"> · {tx.notes}</span>}
            </span>
            <RowMenu
              label={`Azioni per l'operazione del ${formatShortDate(tx.date)}`}
              items={[{ label: 'Elimina operazione', tone: 'danger', onSelect: () => setDeleting(tx) }]}
            />
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={!!deleting}
        title="Eliminare questa operazione?"
        confirmLabel="Elimina"
        pending={deleteAssetTransaction.isPending}
        error={error}
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      >
        {deleting && (
          <>
            {deleting.type === 'buy' ? 'Acquisto' : 'Vendita'} di {formatQuantity(deleting.quantity)} {holding.asset.symbol} del{' '}
            {formatShortDate(deleting.date)}. Posizione e liquidità del conto vengono ricalcolate.
          </>
        )}
      </ConfirmDialog>
    </>
  )
}

/** Every position: quantity, average and current price in the asset's currency, value and weight in base. */
export function HoldingsTable({ holdings, baseCurrency }: { holdings: HoldingWithValue[]; baseCurrency: string }) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const { data: accounts } = useAccounts()
  const accountsById = indexById(accounts)
  const total = holdings.reduce((s, h) => s + Number(h.market_value_base_currency), 0)
  const sorted = [...holdings].sort((a, b) => Number(b.market_value_base_currency) - Number(a.market_value_base_currency))

  if (holdings.length === 0) {
    return <EmptyState title="Nessuna posizione">Registra un acquisto con “+ Nuova operazione” per iniziare.</EmptyState>
  }

  const toggle = (h: HoldingWithValue) => setExpandedId((id) => (id === h.id ? null : h.id))
  const toggleButton = (h: HoldingWithValue) => (
    <button
      type="button"
      onClick={() => toggle(h)}
      aria-expanded={expandedId === h.id}
      aria-label={`Storico operazioni di ${h.asset.symbol}`}
      className="grid h-11 w-11 cursor-pointer place-items-center rounded-[10px] text-ink-2 hover:bg-card-2"
    >
      <ChevronDownIcon className={`h-[18px] w-[18px] transition-transform ${expandedId === h.id ? 'rotate-180' : ''}`} />
    </button>
  )

  return (
    <>
      <div className="relative overflow-x-auto max-md:hidden">
        <table className="w-full min-w-[960px] border-collapse text-[13px] tabular-nums">
          <thead>
            <tr className="text-[12px] text-ink-3">
              <th scope="col" className="border-b border-line py-2 text-left font-bold">Titolo</th>
              <th scope="col" className="border-b border-line py-2 text-right font-bold">Quantità</th>
              <th scope="col" className="border-b border-line py-2 text-right font-bold">Prezzo medio</th>
              <th scope="col" className="border-b border-line py-2 text-right font-bold">Prezzo attuale</th>
              <th scope="col" className="border-b border-line py-2 text-right font-bold">Valore {baseCurrency}</th>
              <th scope="col" className="border-b border-line py-2 text-right font-bold">Peso</th>
              <th scope="col" className="border-b border-line py-2 text-right font-bold">Non realizzato</th>
              <th scope="col" className="w-12 border-b border-line py-2">
                <span className="sr-only">Storico</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((h) => (
              <Fragment key={h.id}>
                <tr>
                  <td className="border-b border-line py-2.5 pr-3">
                    <div className="text-[14px] font-extrabold">
                      {h.asset.symbol}{' '}
                      <span className="ml-0.5 rounded bg-card-2 px-1.5 py-px text-[10px] font-bold text-ink-3 uppercase">{ASSET_TYPE_LABELS[h.asset.asset_type]}</span>
                    </div>
                    <div className="max-w-[260px] truncate text-[12px] text-ink-3">
                      {h.asset.name} · {accountsById.get(h.account_id)?.name ?? 'Conto eliminato'}
                    </div>
                  </td>
                  <td className="border-b border-line py-2.5 text-right text-ink-2">{formatQuantity(h.quantity)}</td>
                  <td className="border-b border-line py-2.5 text-right whitespace-nowrap text-ink-2">
                    {formatAmount(h.avg_buy_price, h.asset.currency)} <span className="ccy">{h.asset.currency}</span>
                  </td>
                  <td className="border-b border-line py-2.5 text-right whitespace-nowrap">
                    {formatAmount(h.current_price, h.asset.currency)} <span className="ccy">{h.asset.currency}</span>
                    <div className="text-[11px] text-ink-3">al {formatShortDate(h.price_date)}</div>
                  </td>
                  <td className="border-b border-line py-2.5 text-right font-bold">{formatAmount(h.market_value_base_currency, baseCurrency)}</td>
                  <td className="border-b border-line py-2.5 text-right text-ink-2">
                    {formatPercent(total ? (Number(h.market_value_base_currency) / total) * 100 : 0)}
                  </td>
                  <td className="border-b border-line py-2.5 text-right">
                    <Delta value={Number(h.unrealized_pnl)} percent={h.unrealized_pnl_percentage} className="block" />
                    <div className="text-[12px] whitespace-nowrap text-ink-3">
                      {formatAmount(h.unrealized_pnl, h.asset.currency, { sign: 'always' })} {h.asset.currency}
                      {Number(h.realized_pnl) !== 0 && ` · realizz. ${formatAmount(h.realized_pnl, h.asset.currency, { sign: 'always' })}`}
                    </div>
                  </td>
                  <td className="border-b border-line py-1 pl-1">{toggleButton(h)}</td>
                </tr>
                {expandedId === h.id && (
                  <tr>
                    <td colSpan={8} className="border-b border-line bg-card-2/60 px-3 py-2">
                      <HoldingHistory holding={h} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {/* Phones: a list, like the D-Mobile portfolio card. */}
      <ul className="md:hidden">
        {sorted.map((h) => (
          <li key={h.id} className="border-t border-line py-2 tabular-nums first:border-t-0">
            <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <div className="font-extrabold">
                  {h.asset.symbol} <span className="ccy">{h.asset.currency}</span>
                </div>
                <div className="truncate text-[12px] text-ink-3">
                  {formatQuantity(h.quantity)} × {formatAmount(h.current_price, h.asset.currency)} · peso{' '}
                  {formatPercent(total ? (Number(h.market_value_base_currency) / total) * 100 : 0)}
                </div>
              </div>
              <div className="text-right">
                <div className="font-bold">
                  {formatAmount(h.market_value_base_currency, baseCurrency)} <span className="ccy">{baseCurrency}</span>
                </div>
                <Delta value={Number(h.unrealized_pnl)} percent={h.unrealized_pnl_percentage} className="text-[12px]" />
              </div>
              {toggleButton(h)}
            </div>
            {expandedId === h.id && (
              <div className="mt-1 rounded-[10px] bg-card-2/60 px-3 py-2">
                <HoldingHistory holding={h} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </>
  )
}
