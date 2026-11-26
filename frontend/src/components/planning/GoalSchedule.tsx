import { StatusChip } from '@/components/ui/StatusChip'
import { Tip } from '@/components/ui/Tip'
import { formatAmount, formatMonthYear, toNumber } from '@/lib/format'
import type { WaterfallStep } from '@/types'

// this_month_amount = giroconti already executed + the suggestion still
// pending (allocated_amount). Said apart, so a suggestion never reads as
// money already set aside.
function thisMonth(step: WaterfallStep, money: (v: string | null) => string): string {
  const pending = toNumber(step.allocated_amount)
  const done = Math.max(0, toNumber(step.this_month_amount) - pending)
  const doneText = money(String(done.toFixed(2)))
  if (done > 0 && pending > 0) return `Questo mese: ${doneText} già versati, puoi accantonarne altri ${money(step.allocated_amount)}.`
  if (done > 0) return `Questo mese: ${doneText} già versati.`
  if (pending > 0) return `Questo mese puoi accantonare ${money(step.allocated_amount)} (da eseguire nelle azioni consigliate).`
  return 'Questo mese non c’è niente da accantonare.'
}

/**
 * A dated goal's timetable, in two parts: what this month puts aside (a
 * one-off from the accounts' surplus included), then what the monthly quota
 * brings from next month — the only part that repeats, so the only one the
 * projection runs on.
 *
 * The status and the deadline stay in sight; the advice sits behind a
 * lightbulb (Tip), so a list of goals doesn't turn into a wall of sentences.
 */
export function GoalSchedule({ step, currency }: { step: WaterfallStep; currency: string }) {
  if (!step.target_date || step.required_monthly === null) return null
  const money = (v: string | null) => `${formatAmount(v, currency)} ${currency}`
  if (step.is_funded) {
    return <p className="mt-1 text-[13px] text-ink-2">Entro {formatMonthYear(step.target_date)} · già pronto.</p>
  }
  const overdue = step.months_left === 0
  const ready = toNumber(step.required_monthly) === 0
  const monthsAfter = Math.max(0, (step.months_left ?? 0) - 1)
  return (
    <div className="mt-1 text-[13px] text-ink-2 tabular-nums">
      <span className="flex flex-wrap items-center gap-x-2">
        <StatusChip kind={step.on_track ? 'good' : 'over'}>{overdue ? 'Scaduto' : step.on_track ? 'In linea' : 'In ritardo'}</StatusChip>
        <span>
          Entro <b className="text-ink">{formatMonthYear(step.target_date)}</b>
          {overdue && ` · mancano ${money(step.gap)}`}
        </span>
        {!overdue && (
          <Tip label="Consiglio per questo obiettivo">
            <span>{thisMonth(step, money)}</span>
            {ready ? (
              <span>{toNumber(step.allocated_amount) > 0 ? 'Eseguendo l’accantonamento di questo mese il target è raggiunto.' : 'Il target è raggiunto.'}</span>
            ) : (
              <span>
                {toNumber(step.allocated_amount) > 0 ? 'Se lo esegui, dal mese prossimo servono' : 'Dal mese prossimo servono'}{' '}
                {money(step.required_monthly)} al mese
                {monthsAfter > 0 ? ` per ${monthsAfter} mesi` : ''}; la quota mensile ne porta {money(step.monthly_pace)}
                {!step.on_track && (step.projected_date ? `: arriva a ${formatMonthYear(step.projected_date)}.` : ': da sola non ci arriva.')}
              </span>
            )}
          </Tip>
        )}
      </span>
    </div>
  )
}
