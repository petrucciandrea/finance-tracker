import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { NetWorthChart } from '@/components/charts/NetWorthChart'
import { MonthPlanCard } from '@/components/dashboard/MonthPlanCard'
import { AllocationBar } from '@/components/portfolio/AllocationBar'
import { Amount, Delta } from '@/components/ui/Amount'
import { Card } from '@/components/ui/Card'
import { EmptyState, ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { SearchIcon } from '@/components/ui/Icon'
import { KpiStrip, type Kpi } from '@/components/ui/KpiStrip'
import { PageHeader } from '@/components/ui/PageHeader'
import { useAccounts } from '@/hooks/useAccounts'
import { useAuth } from '@/hooks/useAuth'
import { useCategories } from '@/hooks/useCategories'
import { useNetWorth, usePortfolioHistory } from '@/hooks/usePortfolio'
import { useAllTransactions, useTransactionsList } from '@/hooks/useTransactions'
import { buttonClass } from '@/lib/buttonClass'
import { indexById } from '@/lib/categories'
import { endOfMonth, monthRange } from '@/lib/dates'
import { formatAmount, formatLongDate, formatMonthName, formatPercent, formatQuantity, formatShortDate, toISODate } from '@/lib/format'
import { ASSET_TYPE_LABELS, INVESTMENT_ACCOUNT_TYPES, unrealizedPnlBase } from '@/lib/portfolio'
import { accountLabel, amountKind, totals } from '@/lib/transactions'
import type { NetWorthSummary } from '@/types'

function PortfolioCard({ netWorth }: { netWorth: NetWorthSummary }) {
  const { data: accounts } = useAccounts()
  const base = netWorth.base_currency
  const holdings = [...netWorth.holdings].sort(
    (a, b) => Number(b.market_value_base_currency) - Number(a.market_value_base_currency),
  )
  const value = Number(netWorth.total_holdings_value)
  const pnl = holdings.reduce((sum, h) => sum + unrealizedPnlBase(h), 0)
  const cost = value - pnl
  const investmentAccounts = new Set(
    (accounts ?? []).filter((a) => INVESTMENT_ACCOUNT_TYPES.includes(a.type)).map((a) => a.id),
  )
  const cash = netWorth.accounts
    .filter((a) => investmentAccounts.has(a.account_id))
    .reduce((sum, a) => sum + Number(a.balance_base_currency), 0)
  const byType: Record<string, number> = { cash }
  for (const h of holdings) {
    byType[h.asset.asset_type] = (byType[h.asset.asset_type] ?? 0) + Number(h.market_value_base_currency)
  }

  return (
    <Card
      title="Portafoglio"
      className="flex-[999_1_600px]"
      meta={
        holdings.length > 0 && (
          <>
            <span className="font-extrabold tabular-nums">
              {formatAmount(value, base)} <span className="ccy">{base}</span>
            </span>
            <span className={`rounded-full px-2 py-0.5 text-[12px] ${pnl >= 0 ? 'bg-pos-soft' : 'bg-neg-soft'}`}>
              <Delta value={pnl} currency={base} percent={cost ? (pnl / cost) * 100 : null} />
            </span>
          </>
        )
      }
      action={
        <Link to="/portfolio" className="link text-[13px]">
          Dettaglio →
        </Link>
      }
    >
      {holdings.length === 0 ? (
        <div className="mt-3">
          <EmptyState title="Nessuna posizione">Registra un acquisto dal Portafoglio per vederlo qui.</EmptyState>
        </div>
      ) : (
        <>
          <div className="mt-3.5">
            <AllocationBar values={byType} currency={base} />
          </div>
          <div className="mt-2.5 relative overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-[13px] tabular-nums">
              <thead>
                <tr className="text-[12px] text-ink-3">
                  <th scope="col" className="border-b border-line py-2 text-left font-bold">Titolo</th>
                  <th scope="col" className="border-b border-line py-2 text-right font-bold">Quantità</th>
                  <th scope="col" className="border-b border-line py-2 text-right font-bold">Prezzo</th>
                  <th scope="col" className="border-b border-line py-2 text-right font-bold">Valore {base}</th>
                  <th scope="col" className="border-b border-line py-2 text-right font-bold">Peso</th>
                  <th scope="col" className="border-b border-line py-2 text-right font-bold">Rendimento</th>
                </tr>
              </thead>
              <tbody>
                {holdings.slice(0, 6).map((h) => (
                  <tr key={h.id}>
                    <td className="border-b border-line py-2.5 pr-3">
                      <div className="text-[14px] font-extrabold">
                        {h.asset.symbol}{' '}
                        <span className="ml-0.5 rounded bg-card-2 px-1.5 py-px text-[10px] font-bold text-ink-3 uppercase">
                          {ASSET_TYPE_LABELS[h.asset.asset_type]}
                        </span>
                      </div>
                      <div className="max-w-[220px] truncate text-[12px] text-ink-3">{h.asset.name}</div>
                    </td>
                    <td className="border-b border-line py-2.5 text-right text-ink-2">{formatQuantity(h.quantity)}</td>
                    <td className="border-b border-line py-2.5 text-right whitespace-nowrap text-ink-2">
                      {formatAmount(h.current_price, h.asset.currency)} <span className="ccy">{h.asset.currency}</span>
                    </td>
                    <td className="border-b border-line py-2.5 text-right font-bold">
                      {formatAmount(h.market_value_base_currency, base)}
                    </td>
                    <td className="border-b border-line py-2.5 text-right text-ink-2">
                      {formatPercent(value ? (Number(h.market_value_base_currency) / value) * 100 : 0)}
                    </td>
                    <td className="border-b border-line py-2.5 text-right">
                      <Delta value={Number(h.unrealized_pnl)} percent={h.unrealized_pnl_percentage} className="block" />
                      <div className="text-[12px] text-ink-3">
                        {formatAmount(h.unrealized_pnl, h.asset.currency, { sign: 'always' })} {h.asset.currency}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {holdings.length > 6 && (
            <p className="mt-2 text-[12px] text-ink-3">
              Prime 6 posizioni su {holdings.length} ·{' '}
              <Link to="/portfolio" className="link">
                vedi tutte
              </Link>
            </p>
          )}
        </>
      )}
    </Card>
  )
}

function RecentTransactions({ baseCurrency }: { baseCurrency: string }) {
  const { data, isLoading } = useTransactionsList({ page: 1, page_size: 7, merge_transfer_legs: true })
  const { data: categories } = useCategories()
  const { data: accounts } = useAccounts()
  const categoriesById = indexById(categories)
  const accountsById = indexById(accounts)
  return (
    <Card
      title="Ultimi movimenti"
      className="flex-[1_1_380px]"
      action={
        <Link to="/transactions" className="link text-[13px]">
          Tutti →
        </Link>
      }
    >
      {isLoading ? (
        <LoadingBlock className="mt-3 h-64" />
      ) : !data?.data.length ? (
        <div className="mt-3">
          <EmptyState title="Nessun movimento" />
        </div>
      ) : (
        <ul className="mt-1.5">
          {data.data.map((t) => (
            <li key={t.id} className="grid grid-cols-[46px_1fr_auto] items-center gap-2.5 border-b border-line py-2.5 tabular-nums">
              <span className="text-[12px] font-semibold text-ink-3">{formatShortDate(t.date)}</span>
              <div className="min-w-0">
                <div className="truncate font-bold">{t.description || '—'}</div>
                <div className="mt-0.5 flex items-center gap-1.5 overflow-hidden text-[12px] whitespace-nowrap text-ink-3">
                  <span className="rounded-full bg-card-2 px-[7px] py-px text-[11px] font-bold text-ink-2">
                    {t.type === 'transfer'
                      ? `⇄ ${categoriesById.get(t.category_id ?? '')?.name ?? 'Trasferimento'}`
                      : (categoriesById.get(t.category_id ?? '')?.name ?? 'Categoria eliminata')}
                  </span>
                  <span className="truncate">{accountLabel(t, accountsById)}</span>
                </div>
              </div>
              <Amount
                value={t.amount}
                currency={t.currency}
                baseValue={t.amount_base_currency}
                baseCurrency={baseCurrency}
                kind={amountKind(t)}
              />
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export function DashboardPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  // Captured once: the dashboard reads "today" for the whole visit.
  const [today] = useState(() => new Date())
  const base = user?.base_currency ?? ''
  const month = formatMonthName(today)

  const netWorth = useNetWorth()
  // Same key as the chart's default period, so this is one request, not
  // two: concurrent history calls on a cold rate cache race on the
  // exchange_rates unique index in the backend and one of them 500s.
  const yearHistory = usePortfolioHistory('1y')
  const monthTx = useAllTransactions(monthRange(today))

  const nw = netWorth.data
  const monthAgo = toISODate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 30))
  const reference = yearHistory.data?.points.find((p) => p.date >= monthAgo)
  const referenceValue = Number(reference?.total_net_worth ?? 0)
  const nwChange = reference && nw ? Number(nw.total_net_worth) - referenceValue : null
  const nwChangePct = nwChange !== null && referenceValue ? (nwChange / Math.abs(referenceValue)) * 100 : null
  const holdingsPnl = nw?.holdings.reduce((sum, h) => sum + unrealizedPnlBase(h), 0) ?? 0
  const holdingsCost = Number(nw?.total_holdings_value ?? 0) - holdingsPnl
  const cashCurrencies = [...new Set(nw?.accounts.map((a) => a.currency))].join(', ')
  const t = totals(monthTx.data ?? [])
  const savings = t.income + t.expense

  const kpis: Kpi[] = [
    {
      label: 'Patrimonio netto',
      value: nw ? formatAmount(nw.total_net_worth, base) : '…',
      sub: nwChange !== null ? <><Delta value={nwChange} currency={base} percent={nwChangePct} /> in 30 gg</> : undefined,
    },
    {
      label: 'Liquidità',
      value: nw ? formatAmount(nw.total_cash_balance, base) : '…',
      sub: nw ? `${nw.accounts.length} conti${cashCurrencies ? ` · ${cashCurrencies}` : ''}` : undefined,
    },
    {
      label: 'Investimenti',
      value: nw ? formatAmount(nw.total_holdings_value, base) : '…',
      sub: holdingsCost ? <><Delta value={holdingsPnl} percent={(holdingsPnl / holdingsCost) * 100} /> non realizzato</> : undefined,
    },
    // Only once there's something to show: most months nobody buys a car.
    ...(nw && nw.physical_assets.length > 0
      ? [
          {
            label: 'Beni',
            value: formatAmount(nw.total_physical_assets_value, base),
            sub: <Link to="/assets" className="link">{`${nw.physical_assets.length} tra veicoli e metalli`}</Link>,
          },
        ]
      : []),
    {
      label: `Entrate · Uscite ${month}`,
      value: monthTx.data ? (
        <>
          <span className="block whitespace-nowrap text-pos">{formatAmount(t.income, base, { sign: 'always' })}</span>
          <span className="block whitespace-nowrap">{formatAmount(t.expense, base)}</span>
        </>
      ) : (
        '…'
      ),
      sub: `${t.incomeCount} entrate · ${t.expenseCount} uscite`,
    },
    {
      label: `Risparmio ${month}`,
      value: <span className="whitespace-nowrap">{monthTx.data ? formatAmount(savings, base) : '…'}</span>,
      tone: savings < 0 ? 'neg' : 'default',
      sub: (
        <span className="whitespace-nowrap">
          {t.income > 0 ? `${formatPercent((savings / t.income) * 100)} delle entrate` : 'nessuna entrata finora'}
        </span>
      ),
      subTone: savings < 0 ? 'neg' : 'muted',
    },
  ]

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const q = new FormData(event.currentTarget).get('q')?.toString().trim()
    navigate(q ? `/transactions?q=${encodeURIComponent(q)}` : '/transactions')
  }

  return (
    <>
      <PageHeader
        title="Panoramica"
        subtitle={`${formatLongDate(today)} ${today.getFullYear()} · giorno ${today.getDate()} di ${endOfMonth(today).getDate()} · importi in ${base} salvo indicazione`}
        actions={
          <>
            <form role="search" onSubmit={onSearch} className="flex min-w-0 flex-[1_1_220px] lg:w-[280px] lg:flex-none">
              <label className="flex min-h-11 w-full items-center gap-2 rounded-[10px] border border-field bg-card px-3 text-ink-3 focus-within:border-accent">
                <SearchIcon />
                <span className="sr-only">Cerca movimenti</span>
                <input name="q" type="search" placeholder="Cerca movimenti…" className="min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-ink-3" />
              </label>
            </form>
            <Link to="/transactions?import=1" className={buttonClass('secondary')}>
              Importa CSV
            </Link>
            <Link to="/transactions?new=1" className={buttonClass('primary')}>
              + Nuova transazione
            </Link>
          </>
        }
      />

      {netWorth.isError && <ErrorBlock>Non è stato possibile caricare il patrimonio.</ErrorBlock>}
      <KpiStrip label="Indicatori principali" items={kpis} />

      <NetWorthChart baseCurrency={base} />

      <MonthPlanCard today={today} />

      <div className="flex flex-wrap gap-4">
        {nw ? <PortfolioCard netWorth={nw} /> : <LoadingBlock className="h-72 flex-[999_1_600px]" />}
        <RecentTransactions baseCurrency={base} />
      </div>
    </>
  )
}
