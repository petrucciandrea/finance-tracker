import { useState } from 'react'
import { ModelEditor } from '@/components/planning/ModelEditor'
import { WaterfallSection } from '@/components/planning/WaterfallSection'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import { ChevronLeftIcon, ChevronRightIcon } from '@/components/ui/Icon'
import { KpiStrip, type Kpi } from '@/components/ui/KpiStrip'
import { PageHeader } from '@/components/ui/PageHeader'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { StatusChip } from '@/components/ui/StatusChip'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { useAllocationHistory } from '@/hooks/useAllocationHistory'
import { useAuth } from '@/hooks/useAuth'
import { useCategories } from '@/hooks/useCategories'
import { useSimulate, useSurvivalBudget } from '@/hooks/usePlanning'
import { addMonths, isSameMonth, monthPace, startOfMonth } from '@/lib/dates'
import { formatAmount, formatMonthName, formatMonthShort, formatMonthYear, formatPercent, toISODate, toNumber } from '@/lib/format'
import { BUCKET_LABELS, bucketKept, bucketStatus, sortBuckets } from '@/lib/planning'
import type { AllocationBucket, AllocationStatus, NecessityLevel, SimulationCut, SurvivalBudget } from '@/types'

const HISTORY_MONTHS = 5
// On phones only the two most recent past months fit beside the bar.
const hideOnMobile = (index: number) => (index >= 2 ? 'max-md:hidden' : '')
const SPEND_BUCKETS: NecessityLevel[] = ['primary', 'useful', 'discretionary']
// Runway bar scale: a year of primary expenses fills it.
const RUNWAY_SCALE = 12

function HistoryCell({ status, bucket }: { status: AllocationStatus | undefined; bucket: AllocationBucket }) {
  const row = status?.buckets.find((b) => b.bucket === bucket)
  const base = 'min-w-[46px] md:min-w-[52px] rounded-md px-0.5 py-1.5 text-center text-[12px]'
  if (!row || Number(row.target_amount) <= 0) return <div className={`${base} bg-card-2 font-semibold text-ink-3`}>—</div>
  const pct = Math.round(row.percentage_used)
  if (!bucketKept(row)) {
    return (
      <div className={`${base} bg-neg-soft font-extrabold text-neg`}>
        {bucket === 'savings' ? '▼' : '▲'} {pct}%<span className="sr-only">, fuori piano</span>
      </div>
    )
  }
  return <div className={`${base} bg-card-2 font-semibold ${pct >= 90 ? 'text-ink' : 'text-ink-3'}`}>{pct}%</div>
}

function AllocationTable({ month, today }: { month: Date; today: Date }) {
  const history = useAllocationHistory(month, HISTORY_MONTHS)
  const current = history[0].query
  const past = history.slice(1)
  const status = current.data
  const inProgress = isSameMonth(month, today)
  const pace = monthPace(month, today)

  return (
    <Card
      title="Ripartizione delle entrate"
      meta={
        status && (
          <span className="text-[13px] text-ink-2 tabular-nums">
            {toNumber(status.flat_rate_tax_total) > 0 ? (
              <>
                su {formatAmount(status.gross_income_total, status.base_currency)} di entrate −{' '}
                {formatAmount(status.flat_rate_tax_total, status.base_currency)} di tasse e contributi P.IVA ={' '}
                <b className="text-ink">{formatAmount(status.income_total, status.base_currency)}</b> {status.base_currency} netti
              </>
            ) : (
              <>
                su <b className="text-ink">{formatAmount(status.income_total, status.base_currency)}</b> {status.base_currency} di entrate
              </>
            )}
          </span>
        )
      }
      action={
        inProgress && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-ink-2">
            <span aria-hidden="true" className="h-3 w-0.5 bg-ink" />
            Ritmo atteso: {formatPercent(pace, { digits: 0 })} del mese
          </span>
        )
      }
    >
      {current.isLoading ? (
        <LoadingBlock className="mt-3 h-48" />
      ) : !status ? (
        <div className="mt-3">
          <ErrorBlock>Non è stato possibile caricare la ripartizione.</ErrorBlock>
        </div>
      ) : (
        <>
          <div className="relative mt-3 overflow-x-auto">
            <table className="w-full border-collapse tabular-nums md:min-w-[900px]">
              <thead>
                <tr className="text-left text-[12px] text-ink-3">
                  <th scope="col" className="border-b border-line pr-3 pb-2 font-bold max-md:hidden">Voce</th>
                  <th scope="col" className="border-b border-line pr-3 pb-2 text-right font-bold max-md:hidden">Target</th>
                  <th scope="col" className="border-b border-line pb-2 font-extrabold text-ink md:w-[30%] md:px-3">
                    {formatMonthYear(month).split(' ')[0]} · {inProgress ? 'in corso' : 'chiuso'}
                  </th>
                  <th scope="col" className="border-b border-line pr-3 pb-2 text-right font-bold max-md:hidden">Margine</th>
                  {past.map(({ month: m }, i) => (
                    <th key={m.toISOString()} scope="col" className={`border-b border-line px-0.5 pb-2 text-center font-bold ${hideOnMobile(i)}`}>
                      {formatMonthShort(m)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortBuckets(status.buckets).map((bucket) => {
                  const chip = bucketStatus(bucket, { pace, closed: !inProgress })
                  const savings = bucket.bucket === 'savings'
                  // Margin as "room left": target − actual for spend, actual − target for savings.
                  const margin = savings ? -Number(bucket.deviation) : Number(bucket.deviation)
                  return (
                    <tr key={bucket.bucket}>
                      <th scope="row" className="border-b border-line py-2.5 pr-3 text-left font-normal whitespace-nowrap max-md:hidden">
                        <div className="font-bold">{BUCKET_LABELS[bucket.bucket]}</div>
                        <div className="text-[12px] text-ink-3">{formatPercent(Number(bucket.percentage))} delle entrate</div>
                      </th>
                      <td className="border-b border-line py-2.5 pr-3 text-right font-semibold max-md:hidden">{formatAmount(bucket.target_amount, status.base_currency)}</td>
                      <td className="border-b border-line py-2.5 pr-2 md:px-3">
                        {/* Below md the row header, target and margin are hidden; the essentials move here. */}
                        <div className="mb-1 flex justify-between gap-2 text-[13px] md:hidden" aria-hidden="true">
                          <span className="font-extrabold">{BUCKET_LABELS[bucket.bucket]}</span>
                          <span className="text-ink-3">target {formatAmount(bucket.target_amount, status.base_currency)}</span>
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                          <StatusChip kind={chip.kind}>{chip.label}</StatusChip>
                          <span className="text-[13px]">
                            <b>{formatAmount(bucket.actual_amount, status.base_currency)}</b>{' '}
                            <span className="text-ink-3">· {formatPercent(bucket.percentage_used, { digits: 0 })}</span>
                          </span>
                        </div>
                        <div className="mt-[7px]">
                          <ProgressBar
                            thick
                            value={bucket.percentage_used}
                            kind={chip.kind}
                            pace={savings || !inProgress ? null : pace}
                            label={`${BUCKET_LABELS[bucket.bucket]}: ${formatPercent(bucket.percentage_used, { digits: 0 })} del target`}
                          />
                        </div>
                      </td>
                      <td className={`border-b border-line py-2.5 pr-3 text-right font-bold max-md:hidden ${margin < 0 ? 'text-neg' : 'text-ink'}`}>
                        {formatAmount(margin, status.base_currency, { sign: 'always' })}
                      </td>
                      {past.map(({ month: m, query }, i) => (
                        <td key={m.toISOString()} className={`border-b border-line px-0.5 py-2.5 ${hideOnMobile(i)}`}>
                          <HistoryCell status={query.data} bucket={bucket.bucket} />
                        </td>
                      ))}
                    </tr>
                  )
                })}
                <tr>
                  <th scope="row" colSpan={3} className="pt-2.5 text-left text-[13px] font-extrabold max-md:hidden">
                    Voci nel piano
                  </th>
                  <td className="pt-2.5 pr-3 text-[13px] font-extrabold md:text-right">
                    <span className="md:hidden">Voci nel piano: </span>
                    {status.buckets.filter((b) => bucketStatus(b, { pace, closed: !inProgress }).kind !== 'over').length}/{status.buckets.length}
                  </td>
                  {past.map(({ month: m, query }, i) => (
                    <td key={m.toISOString()} className={`px-0.5 pt-2.5 text-center text-[13px] font-extrabold text-ink-2 ${hideOnMobile(i)}`}>
                      {query.data && Number(query.data.income_total) > 0
                        ? `${query.data.buckets.filter(bucketKept).length}/${query.data.buckets.length}`
                        : '—'}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          {Number(status.unclassified_amount) > 0 && (
            <div className="mt-3">
              <Notice>
                {formatAmount(status.unclassified_amount, status.base_currency)} {status.base_currency} di spesa senza livello di necessità
                non entra in nessuna voce · piano affidabile al {formatPercent(status.classification_coverage, { digits: 0 })}
              </Notice>
            </div>
          )}
        </>
      )}
    </Card>
  )
}

function RunwayCard({ survival }: { survival: SurvivalBudget | undefined }) {
  const { user } = useAuth()
  if (!survival) return <LoadingBlock className="h-56 flex-[1_1_340px]" />
  const currency = survival.base_currency
  const runway = survival.months_of_runway
  const totalRunway =
    survival.monthly_total_expenses && toNumber(survival.monthly_total_expenses) > 0
      ? toNumber(survival.total_cash_balance) / toNumber(survival.monthly_total_expenses)
      : null
  return (
    <Card title="Autonomia" className="flex-[1_1_340px]">
      <p className="mt-0.5 text-[13px] text-ink-2">Quanto dureresti con la liquidità attuale coprendo solo le spese primarie</p>
      {survival.monthly_primary_expenses === null || runway === null ? (
        <p className="mt-3 rounded-[10px] bg-card-2 px-3 py-2 text-[13px] text-ink-2">
          Serve almeno un mese completo di storico. Le medie ignorano il mese in corso, che è ancora parziale.
        </p>
      ) : (
        <>
          <div className="mt-3 text-[34px] font-extrabold tracking-[-0.02em] tabular-nums">
            {runway.toLocaleString('it-IT', { maximumFractionDigits: 1 })} <span className="text-[16px] font-bold text-ink-2">mesi</span>
          </div>
          <div className="relative mt-2">
            <ProgressBar
              thick
              value={(runway / RUNWAY_SCALE) * 100}
              kind={runway < 3 ? 'over' : runway < 6 ? 'warn' : 'good'}
              label={`${runway.toLocaleString('it-IT', { maximumFractionDigits: 1 })} mesi di autonomia su una scala di ${RUNWAY_SCALE}`}
            />
            <div className="mt-1 flex justify-between text-[11px] font-semibold text-ink-3" aria-hidden="true">
              <span>0</span>
              <span>3</span>
              <span>6</span>
              <span>12+ mesi</span>
            </div>
          </div>
          {totalRunway !== null && (
            <p className="mt-2 text-[13px] text-ink-2">{totalRunway.toLocaleString('it-IT', { maximumFractionDigits: 1 })} mesi mantenendo tutte le spese attuali</p>
          )}
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-line pt-3 text-[13px] tabular-nums">
            <dt className="text-ink-2">Spese primarie / mese</dt>
            <dd className="text-right font-bold">{formatAmount(survival.monthly_primary_expenses, currency)}</dd>
            <dt className="text-ink-2">Spese totali / mese</dt>
            <dd className="text-right">{survival.monthly_total_expenses ? formatAmount(survival.monthly_total_expenses, currency) : '—'}</dd>
            {/* Net of P.IVA taxes, like the plan's base. */}
            <dt className="text-ink-2">{user?.work_type === 'flat_rate' ? 'Entrate nette / mese' : 'Entrate / mese'}</dt>
            <dd className="text-right">{survival.monthly_income ? formatAmount(survival.monthly_income, currency) : '—'}</dd>
            <dt className="text-ink-2">Liquidità</dt>
            <dd className="text-right">{formatAmount(survival.total_cash_balance, currency)}</dd>
          </dl>
          <p className="mt-2 text-[12px] text-ink-3">
            Media su {survival.months_analysed} {survival.months_analysed === 1 ? 'mese completo' : 'mesi completi'}. Il mese in corso è escluso perché
            parziale.
          </p>
        </>
      )}
    </Card>
  )
}

function Simulator({ date, currency }: { date: string; currency: string }) {
  const { data: categories } = useCategories()
  const simulate = useSimulate()
  const [cuts, setCuts] = useState<Record<NecessityLevel, number>>({ primary: 0, useful: 0, discretionary: 0 })
  const [categoryId, setCategoryId] = useState('')
  const [categoryCut, setCategoryCut] = useState(0)
  const result = simulate.data
  const anyCut = Object.values(cuts).some((v) => v > 0) || (!!categoryId && categoryCut > 0)

  function run() {
    const payload: SimulationCut[] = SPEND_BUCKETS.filter((b) => cuts[b] > 0).map((b) => ({ necessity_level: b, cut_percentage: String(cuts[b]) }))
    if (categoryId && categoryCut > 0) payload.push({ category_id: categoryId, cut_percentage: String(categoryCut) })
    simulate.mutate({ date, cuts: payload })
  }

  const money = (v: string | null) => (v === null ? '—' : formatAmount(v, currency))
  const rows = result
    ? [
        { label: 'Spese', before: money(result.total_baseline_spend), after: money(result.total_simulated_spend) },
        { label: 'Risparmio', before: money(result.baseline_savings_amount), after: money(result.simulated_savings_amount) },
        {
          label: 'Tasso di risparmio',
          before: formatPercent(result.baseline_savings_rate),
          after: formatPercent(result.simulated_savings_rate),
        },
        { label: 'Spese primarie / mese', before: money(result.baseline_survival_budget), after: money(result.simulated_survival_budget) },
      ]
    : []

  return (
    <Card title="Simulatore di tagli" className="flex-[999_1_480px]">
      <p className="mt-0.5 text-[13px] text-ink-2">Cosa succede se riduci una voce di spesa, sul mese selezionato</p>
      <div className="mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2">
        <div className="flex flex-col gap-3">
          {SPEND_BUCKETS.map((b) => (
            <label key={b} className="block">
              <span className="flex justify-between text-[14px] font-bold">
                Taglia {BUCKET_LABELS[b].toLowerCase()}
                <span className="tabular-nums text-ink-2">−{cuts[b]}%</span>
              </span>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={cuts[b]}
                onChange={(e) => setCuts({ ...cuts, [b]: Number(e.target.value) })}
                className="mt-1 h-11 w-full cursor-pointer accent-accent"
              />
            </label>
          ))}
          <div className="rounded-[10px] bg-card-2 p-3">
            <p className="text-[12px] text-ink-2">Taglio su una singola categoria: ha la precedenza sul taglio della sua voce.</p>
            <div className="mt-2 flex gap-2">
              <CategorySelect
                aria-label="Categoria da tagliare"
                categories={categories}
                type="expense"
                emptyLabel="Nessuna categoria"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
                className="field min-w-0 flex-1"
              />
              <div className="relative w-24">
                <input
                  type="number"
                  min={0}
                  max={100}
                  aria-label="Percentuale di taglio della categoria"
                  value={categoryCut}
                  onChange={(e) => setCategoryCut(Math.min(100, Math.max(0, Number(e.target.value))))}
                  className="field pr-7"
                />
                <span aria-hidden="true" className="absolute top-1/2 right-3 -translate-y-1/2 text-ink-3">
                  %
                </span>
              </div>
            </div>
          </div>
          <Button variant="primary" onClick={run} disabled={!anyCut || simulate.isPending}>
            {simulate.isPending ? 'Calcolo…' : 'Simula'}
          </Button>
        </div>

        <div aria-live="polite">
          {simulate.isError && <ErrorBlock>Simulazione non riuscita.</ErrorBlock>}
          {result ? (
            <>
              <div className="rounded-[12px] bg-pos-soft px-4 py-3 text-pos">
                <div className="text-[12px] font-bold">Liberati ogni mese</div>
                <div className="text-[26px] font-extrabold tabular-nums">
                  +{formatAmount(result.total_freed, currency)} <span className="text-[12px]">{currency}</span>
                </div>
              </div>
              <table className="mt-3 w-full text-[13px] tabular-nums">
                <thead>
                  <tr className="text-[12px] text-ink-3">
                    <th scope="col" className="pb-1 text-left font-bold">
                      <span className="sr-only">Voce</span>
                    </th>
                    <th scope="col" className="pb-1 text-right font-bold">Prima</th>
                    <th scope="col" className="w-6" aria-hidden="true" />
                    <th scope="col" className="pb-1 text-right font-bold">Dopo</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.label} className="border-t border-line">
                      <th scope="row" className="py-1.5 text-left font-semibold text-ink-2">
                        {r.label}
                      </th>
                      <td className="py-1.5 text-right text-ink-2">{r.before}</td>
                      <td className="text-center text-ink-3" aria-hidden="true">
                        →
                      </td>
                      <td className="py-1.5 text-right font-extrabold">{r.after}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className="rounded-[10px] border border-dashed border-field px-4 py-6 text-center text-[13px] text-ink-3">
              Muovi un cursore e premi “Simula” per vedere l'effetto prima → dopo.
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}

export function PlanningPage() {
  const { user } = useAuth()
  const currency = user?.base_currency ?? ''
  const [today] = useState(() => new Date())
  const [month, setMonth] = useState(() => startOfMonth(new Date()))
  const date = toISODate(month)
  const inProgress = isSameMonth(month, today)

  const history = useAllocationHistory(month, 0)
  const status = history[0].query.data
  const { data: survival } = useSurvivalBudget(date)

  const spend = status
    ? status.buckets.filter((b) => b.bucket !== 'savings').reduce((s, b) => s + toNumber(b.actual_amount), 0) + toNumber(status.unclassified_amount)
    : 0
  const savings = status?.buckets.find((b) => b.bucket === 'savings')
  const excluded = (status?.income_breakdown ?? []).filter((r) => r.excluded_from_income_base).reduce((s, r) => s + toNumber(r.total_amount_base_currency), 0)
  const income = toNumber(status?.income_total)
  // Imposta + INPS on the invoices collected this month: the State's share,
  // already out of the base the whole plan is computed on.
  const flatRateTaxes = toNumber(status?.flat_rate_tax_total)

  const kpis: Kpi[] = [
    {
      label: `${flatRateTaxes > 0 ? 'Entrate nette' : 'Entrate'} ${inProgress ? 'del mese' : `di ${formatMonthName(month)}`}`,
      value: status ? formatAmount(income, currency) : '…',
      sub:
        flatRateTaxes > 0
          ? `${formatAmount(status?.gross_income_total, currency)} lorde − ${formatAmount(flatRateTaxes, currency)} tasse e contributi P.IVA`
          : `base del piano · ${formatAmount(excluded, currency)} esclusi`,
    },
    {
      label: inProgress ? 'Spese finora' : 'Spese',
      value: status ? formatAmount(-spend, currency) : '…',
      sub: income ? `${formatPercent((spend / income) * 100)} delle entrate` : undefined,
    },
    {
      label: inProgress ? 'Risparmio corrente' : 'Risparmio',
      value: savings ? formatAmount(savings.actual_amount, currency) : '…',
      tone: savings && toNumber(savings.actual_amount) < 0 ? 'neg' : 'default',
      sub: savings ? `target ${formatAmount(savings.target_amount, currency)}${inProgress ? ' a fine mese' : ''}` : undefined,
    },
    {
      label: 'Autonomia',
      value: survival?.months_of_runway != null ? `${survival.months_of_runway.toLocaleString('it-IT', { maximumFractionDigits: 1 })} mesi` : '—',
      sub: 'con le sole spese primarie',
    },
    {
      label: 'Classificazione',
      value: status ? formatPercent(status.classification_coverage, { digits: 0 }) : '…',
      sub: status && toNumber(status.unclassified_amount) > 0 ? `${formatAmount(status.unclassified_amount, currency)} ${currency} da classificare` : 'tutta la spesa ha un livello',
      subTone: status && toNumber(status.unclassified_amount) > 0 ? 'warn' : 'muted',
    },
  ]

  return (
    <>
      <PageHeader
        title="Piano"
        subtitle={`Importi in ${currency} · il mese in corso si legge contro il ritmo atteso`}
        actions={
          <div role="group" aria-label="Mese" className="flex items-center gap-1 rounded-[12px] border border-line bg-card p-1">
            <button
              type="button"
              aria-label="Mese precedente"
              onClick={() => setMonth(addMonths(month, -1))}
              className="grid h-10 w-10 cursor-pointer place-items-center rounded-[10px] hover:bg-card-2"
            >
              <ChevronLeftIcon />
            </button>
            <span aria-live="polite" className="min-w-[140px] text-center font-extrabold">
              {formatMonthYear(month)}
            </span>
            <button
              type="button"
              aria-label="Mese successivo"
              disabled={inProgress}
              onClick={() => setMonth(addMonths(month, 1))}
              className="grid h-10 w-10 cursor-pointer place-items-center rounded-[10px] hover:bg-card-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronRightIcon />
            </button>
          </div>
        }
      />

      <KpiStrip label="Indicatori del piano" items={kpis} />
      <ModelEditor />
      <AllocationTable month={month} today={today} />
      <div className="flex flex-wrap gap-4">
        <RunwayCard survival={survival} />
        <Simulator key={date} date={date} currency={currency} />
      </div>
      <WaterfallSection date={date} currency={currency} />
    </>
  )
}
