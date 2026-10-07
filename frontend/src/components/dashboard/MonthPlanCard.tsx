import { Link } from 'react-router-dom'
import { Card } from '@/components/ui/Card'
import { ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { StatusChip } from '@/components/ui/StatusChip'
import { useAllocationHistory } from '@/hooks/useAllocationHistory'
import { monthPace } from '@/lib/dates'
import { formatAmount, formatMonthName, formatMonthShort, formatPercent } from '@/lib/format'
import { BUCKET_LABELS, bucketKept, bucketStatus, modelLabel, sortBuckets } from '@/lib/planning'
import type { AllocationBucket, AllocationStatus } from '@/types'

const HISTORY_MONTHS = 5
// On phones only the two most recent closed months fit beside the bar.
const hideOnMobile = (index: number) => (index >= 2 ? 'max-md:hidden' : '')

function HistoryCell({ status, bucket }: { status: AllocationStatus | undefined; bucket: AllocationBucket }) {
  const row = status?.buckets.find((b) => b.bucket === bucket)
  const base = 'min-w-[46px] md:min-w-[58px] rounded-md px-0.5 py-1.5 text-center text-[12px]'
  if (!row || Number(row.target_amount) <= 0) {
    return <div className={`${base} bg-card-2 font-semibold text-ink-3`}>—</div>
  }
  const pct = Math.round(row.percentage_used)
  if (!bucketKept(row)) {
    const arrow = bucket === 'savings' ? '▼' : '▲'
    return (
      <div className={`${base} bg-neg-soft font-extrabold text-neg`}>
        {arrow} {pct}%<span className="sr-only">, fuori piano</span>
      </div>
    )
  }
  return <div className={`${base} bg-card-2 font-semibold ${pct >= 90 ? 'text-ink' : 'text-ink-3'}`}>{pct}%</div>
}

/**
 * The dashboard's view of the allocation model (budgets are archived): this
 * month's four buckets against target with a pace tick, plus the last five
 * closed months as percentage cells.
 */
export function MonthPlanCard({ today }: { today: Date }) {
  const history = useAllocationHistory(today, HISTORY_MONTHS)
  const current = history[0].query
  const past = history.slice(1)
  const pace = monthPace(today, today)
  const status = current.data

  return (
    <Card
      title={`Piano di ${formatMonthName(today)}`}
      meta={
        status && (
          <span className="text-[13px] text-ink-2 tabular-nums">
            Entrate <b className="text-ink">{formatAmount(status.income_total, status.base_currency)}</b> {status.base_currency} · modello{' '}
            {modelLabel(status.buckets)}
          </span>
        )
      }
      action={
        <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-[12px] text-ink-2">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="h-3 w-0.5 bg-ink" />
            Ritmo atteso: {formatPercent(pace, { digits: 0 })} del mese
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="h-3 w-3 rounded-[3px] bg-warn-soft shadow-[inset_0_0_0_1px_var(--color-warn)]" />
            Sopra il ritmo
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="h-3 w-3 rounded-[3px] bg-neg-soft shadow-[inset_0_0_0_1px_var(--color-neg)]" />
            Fuori piano
          </span>
        </div>
      }
    >
      {current.isLoading ? (
        <LoadingBlock className="mt-3 h-48" />
      ) : current.isError || !status ? (
        <div className="mt-3">
          <ErrorBlock>Non è stato possibile caricare il piano del mese.</ErrorBlock>
        </div>
      ) : (
        <>
          <div className="mt-3 relative overflow-x-auto">
            <table className="w-full border-collapse tabular-nums md:min-w-[820px]">
              <thead>
                <tr className="text-[12px] text-ink-3">
                  <th scope="col" className="border-b border-line pr-3 pb-2 text-left font-bold max-md:hidden">
                    Voce
                  </th>
                  <th scope="col" className="w-[34%] border-b border-line pr-4 pb-2 text-left font-extrabold text-ink">
                    {formatMonthName(today)} · in corso
                  </th>
                  {past.map(({ month }, i) => (
                    <th key={month.toISOString()} scope="col" className={`border-b border-line px-0.5 pb-2 text-center font-bold ${hideOnMobile(i)}`}>
                      {formatMonthShort(month)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortBuckets(status.buckets).map((bucket) => {
                  const chip = bucketStatus(bucket, { pace, closed: false })
                  const savings = bucket.bucket === 'savings'
                  return (
                    <tr key={bucket.bucket}>
                      <th scope="row" className="border-b border-line py-2.5 pr-3 text-left font-normal whitespace-nowrap max-md:hidden">
                        <div className="text-[14px] font-bold">{BUCKET_LABELS[bucket.bucket]}</div>
                        <div className="text-[12px] text-ink-3">
                          {formatPercent(Number(bucket.percentage), { digits: 1 })} · target{' '}
                          {formatAmount(bucket.target_amount, status.base_currency)}
                        </div>
                      </th>
                      <td className="border-b border-line py-2.5 pr-2 md:pr-4">
                        {/* Below md the row header is hidden and its label moves here. */}
                        <div className="mb-1 flex justify-between gap-2 text-[13px] md:hidden" aria-hidden="true">
                          <span className="font-extrabold">{BUCKET_LABELS[bucket.bucket]}</span>
                          <span className="text-ink-3">{formatPercent(Number(bucket.percentage), { digits: 1 })}</span>
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
                            kind={chip.kind === 'good' ? 'good' : chip.kind}
                            pace={savings ? null : pace}
                            label={`${BUCKET_LABELS[bucket.bucket]}: ${formatPercent(bucket.percentage_used, { digits: 0 })} del target`}
                          />
                        </div>
                      </td>
                      {past.map(({ month, query }, i) => (
                        <td key={month.toISOString()} className={`border-b border-line px-0.5 py-2.5 ${hideOnMobile(i)}`}>
                          <HistoryCell status={query.data} bucket={bucket.bucket} />
                        </td>
                      ))}
                    </tr>
                  )
                })}
                <tr>
                  <th scope="row" className="pt-2.5 text-left text-[13px] font-extrabold max-md:hidden">
                    Voci nel piano
                  </th>
                  <td className="pt-2.5 text-[13px] font-extrabold">
                    <span className="md:hidden">Voci nel piano: </span>
                    {status.buckets.filter((b) => bucketStatus(b, { pace, closed: false }).kind !== 'over').length}/
                    {status.buckets.length} <span className="font-medium text-ink-3">finora</span>
                  </td>
                  {past.map(({ month, query }, i) => (
                    <td key={month.toISOString()} className={`px-0.5 pt-2.5 text-center text-[13px] font-extrabold text-ink-2 ${hideOnMobile(i)}`}>
                      {query.data && Number(query.data.income_total) > 0
                        ? `${query.data.buckets.filter(bucketKept).length}/${query.data.buckets.length}`
                        : '—'}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            {Number(status.unclassified_amount) > 0 ? (
              <Notice>
                {formatAmount(status.unclassified_amount, status.base_currency)} {status.base_currency} di spesa senza livello di
                necessità · piano affidabile al {formatPercent(status.classification_coverage, { digits: 0 })}
              </Notice>
            ) : (
              <span />
            )}
            <Link to="/planning" className="link text-[13px]">
              Apri il piano →
            </Link>
          </div>
        </>
      )}
    </Card>
  )
}
