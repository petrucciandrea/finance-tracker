import { useState } from 'react'
import { AllocationBar } from '@/components/portfolio/AllocationBar'
import { DeleteAssetTransactionDialog, EditAssetTransactionDialog } from '@/components/portfolio/AssetTransactionDialogs'
import { AssetTransactionForm } from '@/components/portfolio/AssetTransactionForm'
import { AssetTransactionImport } from '@/components/portfolio/AssetTransactionImport'
import { HoldingsTable } from '@/components/portfolio/HoldingsTable'
import { PnlByAssetChart } from '@/components/portfolio/PnlByAssetChart'
import { PortfolioValueChart } from '@/components/portfolio/PortfolioValueChart'
import { Delta } from '@/components/ui/Amount'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState, ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { UploadIcon } from '@/components/ui/Icon'
import { KpiStrip, type Kpi } from '@/components/ui/KpiStrip'
import { PageHeader } from '@/components/ui/PageHeader'
import { RowMenu } from '@/components/ui/RowMenu'
import { useAccounts } from '@/hooks/useAccounts'
import { useAssetTransactionsList } from '@/hooks/useAssetTransactions'
import { useAuth } from '@/hooks/useAuth'
import { useNetWorth } from '@/hooks/usePortfolio'
import { formatAmount, formatFullDate, formatPercent, formatQuantity, formatShortDate } from '@/lib/format'
import type { AssetTransaction } from '@/types'
import { assetTransactionMenuItems, costBasisBase, INVESTMENT_ACCOUNT_TYPES, realizedPnlBase, unrealizedPnlBase } from '@/lib/portfolio'

type Panel = 'none' | 'form' | 'import'

// Size of the currency move used to illustrate FX exposure.
const FX_SHOCK = 5

function CurrencyExposure({ exposure, baseCurrency }: { exposure: Map<string, number>; baseCurrency: string }) {
  const total = [...exposure.values()].reduce((s, v) => s + v, 0)
  const rows = [...exposure.entries()].filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
  const foreign = rows.find(([ccy]) => ccy !== baseCurrency)
  if (!total) return null
  return (
    <div className="mt-4 border-t border-line pt-3">
      <h3 className="text-[13px] font-extrabold text-ink-2">Esposizione valutaria</h3>
      <ul className="mt-2 flex flex-col gap-1.5 tabular-nums">
        {rows.map(([ccy, value]) => (
          <li key={ccy} className="grid grid-cols-[44px_1fr_auto] items-center gap-2 text-[13px]">
            <span className="font-extrabold">{ccy}</span>
            <span className="h-2 rounded-full bg-track" aria-hidden="true">
              <span className="block h-full rounded-full bg-bar" style={{ width: `${(value / total) * 100}%` }} />
            </span>
            <span className="text-ink-2">
              {formatPercent((value / total) * 100)} · {formatAmount(value, baseCurrency, { digits: 0 })} {baseCurrency}
            </span>
          </li>
        ))}
      </ul>
      {foreign && (
        <p className="mt-2 text-[12px] text-ink-3">
          Un −{FX_SHOCK}% del {foreign[0]} vale circa −{formatAmount((foreign[1] * FX_SHOCK) / 100, baseCurrency, { digits: 0 })} {baseCurrency} sul
          portafoglio.
        </p>
      )}
    </div>
  )
}

function RecentTrades({ baseCurrency }: { baseCurrency: string }) {
  const { data, isLoading } = useAssetTransactionsList()
  const [editing, setEditing] = useState<AssetTransaction | null>(null)
  const [deleting, setDeleting] = useState<AssetTransaction | null>(null)
  const recent = [...(data ?? [])].filter((t) => !t.deleted_at).sort((a, b) => b.date.localeCompare(a.date) || b.created_at.localeCompare(a.created_at)).slice(0, 8)
  return (
    <Card title="Operazioni recenti" className="flex-[1_1_380px]">
      {isLoading ? (
        <LoadingBlock className="mt-3 h-40" />
      ) : recent.length === 0 ? (
        <div className="mt-3">
          <EmptyState title="Nessuna operazione" />
        </div>
      ) : (
        <ul className="mt-1.5">
          {recent.map((t) => (
            <li key={t.id} className="grid grid-cols-[46px_1fr_auto_auto] items-center gap-2.5 border-b border-line py-2.5 tabular-nums last:border-b-0">
              <span className="text-[12px] font-semibold text-ink-3">{formatShortDate(t.date)}</span>
              <div className="min-w-0">
                <div className="font-bold">
                  {t.type === 'buy' ? 'Acquisto' : 'Vendita'} {t.asset.symbol}
                </div>
                <div className="truncate text-[12px] text-ink-3">
                  {formatQuantity(t.quantity)} × {formatAmount(t.price, t.asset.currency)} {t.asset.currency}
                </div>
              </div>
              <span className={`font-extrabold whitespace-nowrap ${t.type === 'sell' ? 'text-pos' : 'text-ink'}`}>
                {formatAmount(t.type === 'buy' ? -Number(t.amount_base_currency) : t.amount_base_currency, baseCurrency, { sign: t.type === 'sell' ? 'always' : 'auto' })}{' '}
                <span className="ccy">{baseCurrency}</span>
              </span>
              <RowMenu
                label={`Azioni per ${t.type === 'buy' ? 'acquisto' : 'vendita'} ${t.asset.symbol} del ${formatShortDate(t.date)}`}
                items={assetTransactionMenuItems(t, { onEdit: setEditing, onDelete: setDeleting })}
              />
            </li>
          ))}
        </ul>
      )}
      <EditAssetTransactionDialog transaction={editing} onClose={() => setEditing(null)} />
      <DeleteAssetTransactionDialog transaction={deleting} onClose={() => setDeleting(null)} />
    </Card>
  )
}

export function PortfolioPage() {
  const { user } = useAuth()
  const base = user?.base_currency ?? ''
  const [today] = useState(() => new Date())
  const [panel, setPanel] = useState<Panel>('none')
  const netWorth = useNetWorth()
  const { data: accounts } = useAccounts()

  const holdings = netWorth.data?.holdings ?? []
  const value = holdings.reduce((s, h) => s + Number(h.market_value_base_currency), 0)
  const cost = holdings.reduce((s, h) => s + costBasisBase(h), 0)
  const unrealized = holdings.reduce((s, h) => s + unrealizedPnlBase(h), 0)
  const realized = holdings.reduce((s, h) => s + realizedPnlBase(h), 0)
  const investmentAccounts = (accounts ?? []).filter((a) => INVESTMENT_ACCOUNT_TYPES.includes(a.type))
  const investmentIds = new Set(investmentAccounts.map((a) => a.id))
  const cashBalances = (netWorth.data?.accounts ?? []).filter((a) => investmentIds.has(a.account_id))
  const cash = cashBalances.reduce((s, a) => s + Number(a.balance_base_currency), 0)

  const byType: Record<string, number> = { cash }
  const exposure = new Map<string, number>()
  for (const h of holdings) {
    byType[h.asset.asset_type] = (byType[h.asset.asset_type] ?? 0) + Number(h.market_value_base_currency)
    exposure.set(h.asset.currency, (exposure.get(h.asset.currency) ?? 0) + Number(h.market_value_base_currency))
  }
  for (const a of cashBalances) exposure.set(a.currency, (exposure.get(a.currency) ?? 0) + Number(a.balance_base_currency))

  const kpis: Kpi[] = [
    {
      label: 'Valore di mercato',
      value: (
        <>
          {formatAmount(value, base)} <span className="ccy">{base}</span>
        </>
      ),
      sub: `${holdings.length} ${holdings.length === 1 ? 'posizione' : 'posizioni'}`,
    },
    { label: 'Capitale investito', value: formatAmount(cost, base), sub: 'costo di carico al cambio di oggi' },
    {
      label: 'Non realizzato',
      value: <Delta value={unrealized} currency={base} />,
      sub: cost ? `${formatPercent((unrealized / cost) * 100, { sign: 'always' })} sul capitale` : undefined,
      subTone: unrealized >= 0 ? 'pos' : 'neg',
    },
    {
      label: 'Realizzato',
      value: formatAmount(realized, base, { sign: realized ? 'always' : 'auto' }),
      tone: realized > 0 ? 'pos' : realized < 0 ? 'neg' : 'default',
      sub: 'sulle posizioni ancora aperte',
    },
    {
      label: 'Liquidità da investire',
      value: formatAmount(cash, base),
      sub: investmentAccounts.map((a) => a.name).join(', ') || 'nessun conto investimento',
    },
  ]

  const toggle = (next: Panel) => setPanel((current) => (current === next ? 'none' : next))

  return (
    <>
      <PageHeader
        title="Portafoglio"
        subtitle={`Prezzi al ${formatFullDate(holdings[0]?.price_date ?? today)} · valori in ${base} salvo indicazione`}
        actions={
          <>
            <Button aria-expanded={panel === 'import'} onClick={() => toggle('import')} className={panel === 'import' ? 'border-accent bg-accent-soft text-accent' : ''}>
              <UploadIcon />
              Importa CSV
            </Button>
            <Button variant="primary" aria-expanded={panel === 'form'} onClick={() => toggle('form')}>
              + Nuova operazione
            </Button>
          </>
        }
      />

      {panel === 'form' && (
        <section aria-label="Nuova operazione">
          <AssetTransactionForm onDone={() => setPanel('none')} />
        </section>
      )}
      {panel === 'import' && (
        <section aria-label="Importa operazioni da CSV">
          <AssetTransactionImport onDone={() => setPanel('none')} />
        </section>
      )}

      {netWorth.isError && <ErrorBlock>Errore nel caricamento del portafoglio.</ErrorBlock>}
      <KpiStrip label="Indicatori del portafoglio" items={kpis} />

      <div className="flex flex-wrap gap-4">
        <PortfolioValueChart baseCurrency={base} />
        <Card title="Allocazione" className="flex-[1_1_320px]">
          <div className="mt-3">
            {value + cash > 0 ? <AllocationBar values={byType} currency={base} /> : <EmptyState title="Nessun investimento" />}
          </div>
          <CurrencyExposure exposure={exposure} baseCurrency={base} />
        </Card>
      </div>

      <Card title="Posizioni" meta={<span className="text-[13px] text-ink-3">Prezzi nella valuta del titolo, valori in {base}</span>}>
        <div className="mt-2">{netWorth.isLoading ? <LoadingBlock className="h-40" /> : <HoldingsTable holdings={holdings} baseCurrency={base} />}</div>
      </Card>

      <div className="flex flex-wrap gap-4">
        <PnlByAssetChart holdings={holdings} baseCurrency={base} />
        <RecentTrades baseCurrency={base} />
      </div>
    </>
  )
}
