import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { useAccounts } from '@/hooks/useAccounts'
import { usePlan, useUpdatePlan } from '@/hooks/usePlanning'
import { apiErrorMessage } from '@/lib/apiError'
import { BUCKET_LABELS, BUCKET_ORDER } from '@/lib/planning'
import type { AllocationPlan } from '@/types'

type Values = Record<'pct_primary' | 'pct_useful' | 'pct_discretionary' | 'pct_savings', string> & {
  lookback_months: string
  default_source_account_id: string
}

const FIELD: Record<(typeof BUCKET_ORDER)[number], keyof Values> = {
  primary: 'pct_primary',
  useful: 'pct_useful',
  discretionary: 'pct_discretionary',
  savings: 'pct_savings',
}

// Shades of one scale for the three spend buckets; savings in the accent.
const SWATCH: Record<(typeof BUCKET_ORDER)[number], string> = {
  primary: 'bg-ink',
  useful: 'bg-ink-2',
  discretionary: 'bg-ink-3',
  savings: 'bg-accent',
}

function fromPlan(plan: AllocationPlan): Values {
  return {
    pct_primary: String(Number(plan.pct_primary)),
    pct_useful: String(Number(plan.pct_useful)),
    pct_discretionary: String(Number(plan.pct_discretionary)),
    pct_savings: String(Number(plan.pct_savings)),
    lookback_months: String(plan.lookback_months),
    default_source_account_id: plan.default_source_account_id ?? '',
  }
}

const toNum = (v: string) => Number(v.replace(',', '.')) || 0

function Editor({ plan, onClose }: { plan: AllocationPlan; onClose: () => void }) {
  const { data: accounts } = useAccounts()
  const updatePlan = useUpdatePlan()
  const [values, setValues] = useState<Values>(() => fromPlan(plan))
  const [error, setError] = useState<string | null>(null)

  // The four percentages move together: the DB constrains them to 100.
  const total = BUCKET_ORDER.reduce((s, b) => s + toNum(values[FIELD[b]]), 0)
  const totalOk = Math.abs(total - 100) < 0.001
  const lookback = Number(values.lookback_months)
  const lookbackOk = Number.isInteger(lookback) && lookback >= 1 && lookback <= 60

  async function save() {
    setError(null)
    try {
      await updatePlan.mutateAsync({
        pct_primary: String(toNum(values.pct_primary)),
        pct_useful: String(toNum(values.pct_useful)),
        pct_discretionary: String(toNum(values.pct_discretionary)),
        pct_savings: String(toNum(values.pct_savings)),
        lookback_months: lookback,
        default_source_account_id: values.default_source_account_id || null,
      })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare il modello.'))
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {BUCKET_ORDER.map((bucket) => (
          <Field key={bucket} label={`${BUCKET_LABELS[bucket]} %`} htmlFor={`pct-${bucket}`}>
            <div className="relative">
              <input
                id={`pct-${bucket}`}
                inputMode="decimal"
                className="field pr-8 tabular-nums"
                aria-invalid={!totalOk}
                aria-describedby="pct-total"
                value={values[FIELD[bucket]]}
                onChange={(e) => setValues({ ...values, [FIELD[bucket]]: e.target.value })}
              />
              <span aria-hidden="true" className="absolute top-1/2 right-3 -translate-y-1/2 text-ink-3">
                %
              </span>
            </div>
          </Field>
        ))}
      </div>

      <div>
        <div className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-track" aria-hidden="true">
          {BUCKET_ORDER.map((bucket) => (
            <span key={bucket} className={`${SWATCH[bucket]} h-full`} style={{ flex: `${Math.max(toNum(values[FIELD[bucket]]), 0)} 1 0` }} />
          ))}
          {total < 100 && <span className="h-full" style={{ flex: `${100 - total} 1 0` }} />}
        </div>
        <p id="pct-total" role="status" className={`mt-1.5 text-[13px] font-bold tabular-nums ${totalOk ? 'text-ink-2' : 'text-neg'}`}>
          {totalOk ? '✓ Totale 100%' : `✕ Totale ${total.toLocaleString('it-IT', { maximumFractionDigits: 2 })}%: deve fare esattamente 100`}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Mesi di storico per le medie" htmlFor="lookback" error={lookbackOk ? undefined : 'Tra 1 e 60 mesi'}>
          <input
            id="lookback"
            type="number"
            min={1}
            max={60}
            className="field"
            aria-invalid={!lookbackOk}
            value={values.lookback_months}
            onChange={(e) => setValues({ ...values, lookback_months: e.target.value })}
          />
        </Field>
        <Field label="Conto da cui partono i giroconti" htmlFor="source-account">
          <select
            id="source-account"
            className="field"
            value={values.default_source_account_id}
            onChange={(e) => setValues({ ...values, default_source_account_id: e.target.value })}
          >
            <option value="">Nessuno</option>
            {/* A closed account stays listed only while it's the saved choice, so the select doesn't silently show "Nessuno". */}
            {(accounts ?? [])
              .filter((a) => !a.closed_at || a.id === values.default_source_account_id)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} · {a.currency}
                  {a.closed_at ? ' (chiuso)' : ''}
                </option>
              ))}
          </select>
        </Field>
      </div>

      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex flex-wrap justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={save} disabled={!totalOk || !lookbackOk || updatePlan.isPending}>
          {updatePlan.isPending ? 'Salvataggio…' : 'Salva modello'}
        </Button>
      </div>
    </div>
  )
}

/** The 4-way split, editable. Changing it re-reads the current period — a plan is prospective. */
export function ModelEditor() {
  const { data: plan } = usePlan()
  const [editing, setEditing] = useState(false)
  return (
    <Card
      title="Modello di ripartizione"
      action={
        !editing && (
          <Button size="sm" onClick={() => setEditing(true)} disabled={!plan}>
            Modifica
          </Button>
        )
      }
    >
      {plan && editing ? (
        <Editor plan={plan} onClose={() => setEditing(false)} />
      ) : plan ? (
        <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-ink-2 tabular-nums">
          {BUCKET_ORDER.map((bucket) => (
            <li key={bucket} className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-[3px] ${SWATCH[bucket]}`} />
              {BUCKET_LABELS[bucket]} <b className="text-ink">{Number(plan[FIELD[bucket] as keyof AllocationPlan]).toLocaleString('it-IT')}%</b>
            </li>
          ))}
          <li>
            Medie su <b className="text-ink">{plan.lookback_months} mesi</b>
          </li>
        </ul>
      ) : null}
    </Card>
  )
}
