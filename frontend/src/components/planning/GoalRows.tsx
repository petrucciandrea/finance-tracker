/**
 * The rows the plan's pillars are built from: a goal, the tax provision, a
 * suggested giroconto, plus the goal and source forms. Kept apart from
 * PillarsSection so that file stays about layout and selection state.
 */
import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { CloseIcon } from '@/components/ui/Icon'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { StatusChip } from '@/components/ui/StatusChip'
import { useAccounts } from '@/hooks/useAccounts'
import { useHoldings } from '@/hooks/usePortfolio'
import { useAddGoalSource, useCreateGoal, useRemoveGoalSource } from '@/hooks/useSavingsGoals'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatPercent, toISODate, toNumber } from '@/lib/format'
import { actionKey, resolve, type Choice } from '@/lib/waterfallActions'
import type { Account, SavingsGoal, SavingsGoalKind, TargetMode, TaxProvisionRung, WaterfallAction, WaterfallStep } from '@/types'
import { GoalSchedule } from '@/components/planning/GoalSchedule'
import { Tip } from '@/components/ui/Tip'
import { PILLAR_OF_KIND, sourceLabel } from '@/lib/goals'

const TARGET_MODE_LABELS: Record<TargetMode, string> = {
  months_of_primary_expenses: 'Mesi di spese primarie',
  fixed_amount: 'Importo fisso',
  open_ended: 'Senza target (assorbe il residuo)',
}

export function StepRow({ step, index, goal, currency }: { step: WaterfallStep; index: number; goal?: SavingsGoal; currency: string }) {
  const { data: accounts } = useAccounts()
  const sources = (goal?.sources ?? []).map((s) => sourceLabel(s, accounts))
  const money = (v: string | null) => (v === null ? '—' : `${formatAmount(v, currency)} ${currency}`)
  return (
    <div className="grid grid-cols-[32px_1fr] gap-3 py-3">
      <span
        aria-hidden="true"
        className={`grid h-8 w-8 place-items-center rounded-full text-[13px] font-extrabold ${
          step.is_funded ? 'bg-pos-soft text-pos' : 'bg-card-2 text-ink-2'
        }`}
      >
        {step.is_funded ? '✓' : index + 1}
      </span>
      <div className="min-w-0 tabular-nums">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="font-extrabold">
            <span className="sr-only">Priorità {index + 1}: </span>
            {step.name}
          </span>
          <span className="flex flex-wrap gap-1.5">
            {Number(step.allocated_amount) > 0 && <StatusChip kind="info">+{money(step.allocated_amount)} da versare</StatusChip>}
            {step.is_funded && <StatusChip kind="good">Completo</StatusChip>}
          </span>
        </div>
        {step.target_unavailable ? (
          <p className="mt-1 text-[13px] font-semibold text-warn">
            Target non ancora calcolabile{' '}
            <Tip label="Perché non è calcolabile">
              Serve almeno un mese completo di storico per la media delle spese primarie. L’obiettivo è sospeso, non considerato completo.
            </Tip>
          </p>
        ) : step.target_amount === null ? (
          <p className="mt-1 text-[13px] text-ink-2">Senza target: riceve tutto ciò che avanza dagli obiettivi sopra. Ora {money(step.current_amount)}.</p>
        ) : (
          <>
            <div className="mt-1 flex justify-between text-[13px] text-ink-2">
              <span>
                <b className="text-ink">{money(step.current_amount)}</b> su {money(step.target_amount)}
              </span>
              <span>{formatPercent(step.funding_percentage, { digits: 0 })}</span>
            </div>
            <div className="mt-1.5">
              <ProgressBar
                value={step.funding_percentage}
                kind={step.is_funded ? 'good' : 'ok'}
                label={`${step.name}: ${formatPercent(step.funding_percentage, { digits: 0 })} del target`}
              />
            </div>
          </>
        )}
        <GoalSchedule step={step} currency={currency} />
        {step.has_unpriced_sources && (
          <p className="mt-1 text-[13px] font-semibold text-warn">
            Un investimento collegato non ha un prezzo salvato{' '}
            <Tip label="Cosa fare">Apri il Portafoglio per aggiornarlo. Finché manca il prezzo non è contato.</Tip>
          </p>
        )}
        <p className="mt-1 text-[12px] text-ink-3">{sources.length ? `Fonti: ${sources.join(', ')}` : 'Nessuna fonte collegata'}</p>
      </div>
    </div>
  )
}

export function TaxRow({ rung, currency }: { rung: TaxProvisionRung; currency: string }) {
  const money = (v: string) => `${formatAmount(v, currency)} ${currency}`
  const pct = toNumber(rung.target) > 0 ? Math.min(100, (toNumber(rung.current) / toNumber(rung.target)) * 100) : 100
  const covered = toNumber(rung.gap) <= 0
  return (
    <li className="grid grid-cols-[32px_1fr] gap-3 py-3">
      <span aria-hidden="true" className={`grid h-8 w-8 place-items-center rounded-full text-[13px] font-extrabold ${covered ? 'bg-pos-soft text-pos' : 'bg-card-2 text-ink-2'}`}>
        {covered ? '✓' : '€'}
      </span>
      <div className="min-w-0 tabular-nums">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="font-extrabold">
            Accantonamento tasse <span className="text-[12px] font-semibold text-ink-3">servito prima di tutti i pilastri: è un debito</span>
          </span>
          <span className="flex flex-wrap gap-1.5">
            {toNumber(rung.allocated_amount) > 0 && <StatusChip kind="info">+{money(rung.allocated_amount)} da versare</StatusChip>}
            {covered && <StatusChip kind="good">Coperto</StatusChip>}
          </span>
        </div>
        <div className="mt-1 flex justify-between text-[13px] text-ink-2">
          <span>
            <b className="text-ink">{money(rung.current)}</b> su {money(rung.target)} che chiederanno gli F24
          </span>
          <span>{formatPercent(pct, { digits: 0 })}</span>
        </div>
        <div className="mt-1.5">
          <ProgressBar value={pct} kind={covered ? 'good' : 'ok'} label={`Accantonamento tasse: ${Math.round(pct)}%`} />
        </div>
        {rung.account_name && <p className="mt-1 text-[12px] text-ink-3">Conto: {rung.account_name}</p>}
      </div>
    </li>
  )
}

export function ActionRow({
  action,
  accounts,
  choice,
  onChoose,
  selected,
  onToggle,
}: {
  action: WaterfallAction
  accounts: Account[]
  choice: Choice | undefined
  onChoose: (choice: Choice) => void
  selected: boolean
  onToggle: () => void
}) {
  const r = resolve(action, choice, accounts)
  const money = `${formatAmount(action.amount, action.currency)} ${action.currency}`
  const open = accounts.filter((a) => !a.closed_at)
  const key = actionKey(action)
  return (
    <li className={`rounded-[10px] border px-3 py-2.5 ${r.executable ? 'border-line bg-card' : 'border-dashed border-field bg-card-2'}`}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          aria-label={`Esegui: ${money} verso ${action.goal_name}`}
          checked={r.executable && selected}
          disabled={!r.executable}
          onChange={onToggle}
          className="mt-1 h-[18px] w-[18px] flex-none accent-accent disabled:opacity-40"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-bold tabular-nums">
              ⇄ {money} verso «{action.goal_name}»
            </span>
            <StatusChip kind={r.executable ? 'info' : 'warn'}>{r.executable ? 'Giroconto' : 'Da completare'}</StatusChip>
          </div>
          <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-0.5 text-[12px] text-ink-2">
              Da
              <select className="field h-9 py-0" value={r.from ?? ''} onChange={(e) => onChoose({ ...choice, from: e.target.value || undefined })} id={`wf-from-${key}`}>
                <option value="">Scegli…</option>
                {open.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} · {a.currency}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-0.5 text-[12px] text-ink-2">
              {r.linking ? 'A (diventa il conto dell’obiettivo)' : 'A'}
              {r.linking ? (
                <select className="field h-9 py-0" value={r.to ?? ''} onChange={(e) => onChoose({ ...choice, to: e.target.value || undefined })} id={`wf-to-${key}`}>
                  <option value="">Scegli…</option>
                  {open.filter((a) => a.id !== r.from).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {a.currency}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="field flex h-9 items-center py-0 text-ink">{action.to_account_name}</span>
              )}
            </label>
          </div>
          {/* The backend's reason ends with the context after "— "; what's
              missing is worked out here instead, from the user's picks. */}
          <p className="mt-1 text-[13px] text-ink-2">{r.problem ?? action.reason.replace(/^.*— /, '')}</p>
        </div>
      </div>
    </li>
  )
}

export function GoalForm({ onDone, initialKind = 'emergency_fund' }: { onDone: () => void; initialKind?: SavingsGoalKind }) {
  const createGoal = useCreateGoal()
  const [name, setName] = useState('')
  const [kind, setKind] = useState<SavingsGoalKind>(initialKind)
  // The emergency fund is sized in months of primary spend; the rest in money.
  const [targetMode, setTargetMode] = useState<TargetMode>(initialKind === 'emergency_fund' ? 'months_of_primary_expenses' : 'fixed_amount')
  const [months, setMonths] = useState('6')
  const [amount, setAmount] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [error, setError] = useState<string | null>(null)
  const canHaveDate = kind === 'medium_term' && targetMode === 'fixed_amount'
  // "Whatever is left" is pillar 4's job: open-ended elsewhere is a 422.
  const modes = (Object.keys(TARGET_MODE_LABELS) as TargetMode[]).filter((m) => m !== 'open_ended' || kind === 'long_term')

  function chooseKind(next: SavingsGoalKind) {
    setKind(next)
    if (targetMode === 'open_ended' && next !== 'long_term') setTargetMode('fixed_amount')
  }

  async function submit() {
    setError(null)
    if (!name.trim()) return setError('Il nome è obbligatorio')
    try {
      await createGoal.mutateAsync({
        name: name.trim(),
        // No priority: the server places it in its pillar (a dated goal by
        // date, nearest first) and the menu moves it from there.
        kind,
        target_mode: targetMode,
        target_months: targetMode === 'months_of_primary_expenses' ? months : null,
        target_amount: targetMode === 'fixed_amount' ? amount.replace(',', '.') : null,
        target_date: canHaveDate && targetDate ? targetDate : null,
      })
      onDone()
    } catch (e) {
      setError(apiErrorMessage(e, "Impossibile creare l'obiettivo."))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nome" htmlFor="goal-name">
          <input id="goal-name" className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Es. Fondo emergenza" />
        </Field>
        <Field label="Pilastro" htmlFor="goal-kind">
          <select id="goal-kind" className="field" value={kind} onChange={(e) => chooseKind(e.target.value as SavingsGoalKind)}>
            {(Object.keys(PILLAR_OF_KIND) as SavingsGoalKind[]).map((k) => (
              <option key={k} value={k}>
                {PILLAR_OF_KIND[k].number} · {PILLAR_OF_KIND[k].title}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Target" htmlFor="goal-mode">
          <select id="goal-mode" className="field" value={targetMode} onChange={(e) => setTargetMode(e.target.value as TargetMode)}>
            {modes.map((m) => (
              <option key={m} value={m}>
                {TARGET_MODE_LABELS[m]}
              </option>
            ))}
          </select>
        </Field>
        {targetMode === 'months_of_primary_expenses' && (
          <Field label="Mesi" htmlFor="goal-months">
            <input id="goal-months" type="number" min={1} className="field" value={months} onChange={(e) => setMonths(e.target.value)} />
          </Field>
        )}
        {targetMode === 'fixed_amount' && (
          <Field label="Importo" htmlFor="goal-amount">
            <input id="goal-amount" inputMode="decimal" className="field" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
        )}
        {canHaveDate && (
          <Field label="Entro il" htmlFor="goal-date" hint="Facoltativa: calcola la rata mensile che serve.">
            <input id="goal-date" type="date" className="field" min={toISODate(new Date())} value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
          </Field>
        )}
      </div>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>Annulla</Button>
        <Button variant="primary" onClick={submit} disabled={createGoal.isPending}>
          {createGoal.isPending ? 'Creazione…' : 'Crea obiettivo'}
        </Button>
      </div>
    </div>
  )
}

function GoalSourcesForm({ goal }: { goal: SavingsGoal }) {
  const { data: accounts } = useAccounts()
  // Only mounted while the dialog is open: listing holdings prices them live.
  const { data: holdings } = useHoldings()
  const addSource = useAddGoalSource()
  const removeSource = useRemoveGoalSource()
  const [choice, setChoice] = useState('')
  const [error, setError] = useState<string | null>(null)
  const linked = new Set(goal.sources.map((s) => `${s.account_id}:${s.asset_id ?? ''}`))

  const options = [
    ...(accounts ?? [])
      .filter((a) => !a.closed_at)
      .map((a) => ({ value: `${a.id}:`, label: `${a.name} · liquidità ${a.currency}` })),
    ...(holdings ?? []).map((h) => ({
      value: `${h.account_id}:${h.asset.id}`,
      label: `${h.asset.symbol} in ${accounts?.find((a) => a.id === h.account_id)?.name ?? 'conto'}`,
    })),
  ].filter((o) => !linked.has(o.value))

  async function add() {
    if (!choice) return
    const [accountId, assetId] = choice.split(':')
    setError(null)
    try {
      await addSource.mutateAsync({ goalId: goal.id, accountId, assetId: assetId || null })
      setChoice('')
    } catch (e) {
      // 409 when it already funds another goal or holds the tax provision.
      setError(apiErrorMessage(e, 'Impossibile collegare la fonte.'))
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {goal.sources.length === 0 ? (
        <p className="text-[14px] text-ink-3">Nessuna fonte collegata.</p>
      ) : (
        <ul>
          {goal.sources.map((source) => (
            <li key={source.id} className="flex items-center justify-between border-t border-line py-1 first:border-t-0">
              <span className="font-semibold">{sourceLabel(source, accounts)}</span>
              <button
                type="button"
                onClick={() => removeSource.mutateAsync({ goalId: goal.id, sourceId: source.id })}
                disabled={removeSource.isPending}
                aria-label="Scollega la fonte"
                className="grid h-11 w-11 cursor-pointer place-items-center rounded-[10px] text-ink-2 hover:bg-card-2"
              >
                <CloseIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <label htmlFor="goal-source" className="sr-only">
          Fonte da collegare
        </label>
        <select id="goal-source" className="field min-w-0 flex-1" value={choice} onChange={(e) => setChoice(e.target.value)}>
          <option value="">Collega un conto o un investimento…</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <Button variant="primary" onClick={add} disabled={!choice || addSource.isPending}>
          Collega
        </Button>
      </div>
      {error && <ErrorBlock>{error}</ErrorBlock>}
    </div>
  )
}

export function GoalSourcesDialog({ goal, onClose }: { goal: SavingsGoal | null; onClose: () => void }) {
  return (
    <Dialog
      open={!!goal}
      onClose={onClose}
      title={`Fonti di “${goal?.name ?? ''}”`}
      description={
        <>
          Il saldo dei conti, o il valore degli investimenti, conta come già accantonato.{' '}
          <Tip>
            Un conto può finanziare più obiettivi: il saldo li riempie in ordine di pilastro e di priorità e quello che avanza diventa eccedenza. Un investimento
            finanzia un solo obiettivo.
          </Tip>
        </>
      }
    >
      {goal && <GoalSourcesForm goal={goal} />}
    </Dialog>
  )
}
