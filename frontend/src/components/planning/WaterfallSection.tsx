import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { CloseIcon } from '@/components/ui/Icon'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { RowMenu } from '@/components/ui/RowMenu'
import { StatusChip } from '@/components/ui/StatusChip'
import { useAccounts } from '@/hooks/useAccounts'
import { useHoldings } from '@/hooks/usePortfolio'
import {
  useAddGoalSource,
  useCreateGoal,
  useDeleteGoal,
  useExecuteWaterfall,
  useRemoveGoalSource,
  useSavingsGoals,
  useUpdateGoal,
  useWaterfall,
} from '@/hooks/useSavingsGoals'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatFullDate, formatPercent, toISODate, toNumber } from '@/lib/format'
import type { Account, SavingsGoal, SavingsGoalKind, TargetMode, TaxProvisionRung, WaterfallAction, WaterfallStep } from '@/types'
import { GoalSchedule } from '@/components/planning/GoalSchedule'
import { Tip } from '@/components/ui/Tip'
import { PILLAR_OF_KIND, sourceLabel } from '@/lib/goals'

const TARGET_MODE_LABELS: Record<TargetMode, string> = {
  months_of_primary_expenses: 'Mesi di spese primarie',
  fixed_amount: 'Importo fisso',
  open_ended: 'Senza target (assorbe il residuo)',
}

function StepRow({ step, index, goal, currency }: { step: WaterfallStep; index: number; goal?: SavingsGoal; currency: string }) {
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

// A goal's id (or the purpose, for the tax provision) plus the suggested
// source: one goal can be fed from several accounts — the spending account and a
// goal account's excess — and each is its own giroconto.
function actionKey(a: WaterfallAction): string {
  return `${a.goal_id ?? a.purpose}:${a.from_account_id ?? ''}`
}

function TaxRow({ rung, currency }: { rung: TaxProvisionRung; currency: string }) {
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
            Accantonamento tasse <span className="text-[12px] font-semibold text-ink-3">è un debito, non un obiettivo</span>
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

interface Resolved {
  from: string | null
  to: string | null
  // The destination is picked here and will be linked to the goal.
  linking: boolean
  executable: boolean
  problem: string | null
}

// What the row will do once the user's picks are applied on top of the
// suggestion: the source can always be changed; a destination only when the
// goal has none (it then becomes the goal's account).
function resolve(action: WaterfallAction, choice: Choice | undefined, accounts: Account[]): Resolved {
  const from = choice?.from ?? action.from_account_id
  const linking = action.to_account_id === null && action.purpose === 'goal'
  const to = action.to_account_id ?? choice?.to ?? null
  const fromAccount = accounts.find((a) => a.id === from)
  const toAccount = accounts.find((a) => a.id === to)
  let problem: string | null = null
  if (!from) problem = 'Scegli il conto da cui partire'
  else if (!to) problem = 'Scegli il conto in cui mettere questi soldi: verrà collegato all’obiettivo'
  else if (from === to) problem = 'Partenza e destinazione sono lo stesso conto'
  else if (fromAccount && toAccount && fromAccount.currency !== toAccount.currency)
    problem = `Valute diverse (${fromAccount.currency} → ${toAccount.currency}): fallo a mano con un cambio`
  return { from, to, linking, executable: problem === null, problem }
}

type Choice = { from?: string; to?: string }

function ActionRow({
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

function GoalForm({ onDone }: { onDone: () => void }) {
  const createGoal = useCreateGoal()
  const [name, setName] = useState('')
  const [kind, setKind] = useState<SavingsGoalKind>('emergency_fund')
  const [targetMode, setTargetMode] = useState<TargetMode>('months_of_primary_expenses')
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

function GoalSourcesDialog({ goal, onClose }: { goal: SavingsGoal | null; onClose: () => void }) {
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

/**
 * The month's money moved into the pillars: the tax provision first (a
 * debt), then pillars 2 → 3 → 4, and inside each the goals in priority order,
 * spilling to the next only when the one above is full. Suggested giroconti
 * are pre-selected and run as one all-or-nothing batch.
 */
export function WaterfallSection({ date, currency }: { date: string; currency: string }) {
  const { data: waterfall, isLoading, isError } = useWaterfall(date)
  const { data: goals } = useSavingsGoals()
  const deleteGoal = useDeleteGoal()
  const updateGoal = useUpdateGoal()
  const executeWaterfall = useExecuteWaterfall()
  const [goalError, setGoalError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [editingSources, setEditingSources] = useState<SavingsGoal | null>(null)
  const [deleting, setDeleting] = useState<SavingsGoal | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deselected, setDeselected] = useState<Set<string>>(new Set())
  const [executeError, setExecuteError] = useState<string | null>(null)

  const { data: accountList } = useAccounts()
  const accounts = accountList ?? []
  // The user's per-row picks (source, and destination for a goal with no
  // account), keyed like the selection. Lost on reload, on purpose: the
  // suggestions may have moved.
  const [choices, setChoices] = useState<Record<string, Choice>>({})
  const goalsById = new Map((goals ?? []).map((g) => [g.id, g]))
  const actions = waterfall?.actions ?? []
  const executableActions = actions.filter((a) => resolve(a, choices[actionKey(a)], accounts).executable)
  // Selected by default — acting on the suggestions is the common case.
  // Tracking the opt-outs keeps the set right when the suggestions recompute.
  const selected = new Set(executableActions.map(actionKey).filter((id) => !deselected.has(id)))

  function toggle(goalId: string) {
    setDeselected((current) => {
      const next = new Set(current)
      if (next.has(goalId)) next.delete(goalId)
      else next.add(goalId)
      return next
    })
  }

  async function runExecute() {
    setExecuteError(null)
    const items = executableActions
      .filter((a) => selected.has(actionKey(a)))
      .map((a) => {
        const r = resolve(a, choices[actionKey(a)], accounts)
        const from_account_id = r.from as string
        if (a.purpose === 'tax_provision') return { to_account_id: r.to as string, from_account_id, amount: a.amount }
        // A destination is sent only when it is being linked to the goal.
        return { goal_id: a.goal_id as string, from_account_id, amount: a.amount, ...(r.linking ? { to_account_id: r.to as string } : {}) }
      })
    if (items.length === 0) return
    try {
      await executeWaterfall.mutateAsync({ date, items })
      setDeselected(new Set())
      setChoices({})
    } catch (e) {
      // The backend applies the batch all-or-nothing, so nothing landed.
      setExecuteError(apiErrorMessage(e, 'Impossibile eseguire i giroconti.'))
    }
  }

  async function confirmDelete() {
    if (!deleting) return
    setDeleteError(null)
    try {
      await deleteGoal.mutateAsync(deleting.id)
      setDeleting(null)
    } catch (e) {
      setDeleteError(apiErrorMessage(e))
    }
  }

  // Already in the server's order: pillar, then priority inside it. Sorting
  // by `priority` alone here would mix the pillars again.
  const steps = waterfall?.steps ?? []
  const groups = (Object.keys(PILLAR_OF_KIND) as SavingsGoalKind[])
    .map((kind) => ({ kind, steps: steps.filter((s) => s.kind === kind) }))
    .filter((g) => g.steps.length > 0)
  const completed = (goals ?? []).filter((g) => g.completed_at)

  async function patchGoal(id: string, payload: Parameters<typeof updateGoal.mutateAsync>[0]['payload']) {
    setGoalError(null)
    try {
      await updateGoal.mutateAsync({ id, payload })
    } catch (e) {
      setGoalError(apiErrorMessage(e, "Impossibile aggiornare l'obiettivo."))
    }
  }

  // Swap with the neighbour in the same pillar (the pillar is fixed by the
  // kind, priority only orders inside it), then renumber 0..n so ties
  // (priority isn't unique) can't make the move a no-op. Only the rows that
  // changed are sent.
  async function move(goalId: string, direction: -1 | 1) {
    const order = steps.map((s) => s.goal_id)
    const index = order.indexOf(goalId)
    const target = index + direction
    if (index < 0 || target < 0 || target >= order.length || steps[target].kind !== steps[index].kind) return
    ;[order[index], order[target]] = [order[target], order[index]]
    setGoalError(null)
    try {
      for (const [priority, id] of order.entries()) {
        if (steps.find((s) => s.goal_id === id)?.priority !== priority) {
          await updateGoal.mutateAsync({ id, payload: { priority } })
        }
      }
    } catch (e) {
      setGoalError(apiErrorMessage(e, 'Impossibile spostare l’obiettivo.'))
    }
  }

  return (
    <Card
      title="Versamenti del mese"
      meta={
        <Tip>
          <span>
            Si distribuisce la quota di risparmio del mese o, se è di più, quello che i conti di spesa hanno oltre la liquidità del primo pilastro:
            prima le tasse, che sono un debito, poi il fondo emergenza, gli accantonamenti e infine gli investimenti. Dentro ogni pilastro gli
            obiettivi seguono la loro priorità, e si passa al successivo solo quando quello sopra è pieno (al 95%).
          </span>
          <span>Gli obiettivi con una scadenza entrano in ordine di data; dal menu puoi spostarli dentro il loro pilastro.</span>
        </Tip>
      }
      action={
        <Button variant="secondary" onClick={() => setAdding(true)}>
          + Nuovo obiettivo
        </Button>
      }
    >
      {isLoading ? (
        <LoadingBlock className="mt-3 h-40" />
      ) : isError || !waterfall ? (
        <div className="mt-3">
          <ErrorBlock>Non è stato possibile calcolare i versamenti del mese.</ErrorBlock>
        </div>
      ) : (
        <>
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px] tabular-nums">
            {[
              ['Quota di risparmio', waterfall.savings_quota],
              ...(waterfall.operating_surplus !== null ? [['Eccedenza sui conti di spesa', waterfall.operating_surplus]] : []),
              ...(toNumber(waterfall.goal_account_excess) > 0 ? [['Eccedenza sui conti obiettivo', waterfall.goal_account_excess]] : []),
              ['Da distribuire', waterfall.budget],
              ['Già allocato', waterfall.already_allocated],
              ['Avanzo', waterfall.unallocated_amount],
            ].map(([label, value]) => (
              <div key={label} className="flex gap-1.5">
                <dt className="text-ink-2">{label}</dt>
                <dd className="font-extrabold">
                  {formatAmount(value, currency)} <span className="ccy">{currency}</span>
                </dd>
              </div>
            ))}
          </dl>

          <div className="mt-3 flex flex-wrap gap-6">
            <div className="min-w-0 flex-[999_1_420px]">
              {steps.length === 0 ? (
                <EmptyState title="Nessun obiettivo" action={<Button variant="primary" onClick={() => setAdding(true)}>Crea il primo obiettivo</Button>}>
                  Parti da un fondo emergenza di qualche mese di spese primarie.
                </EmptyState>
              ) : (
                <div className="flex flex-col gap-3">
                  {waterfall.tax_provision && (
                    <section aria-labelledby="wf-taxes">
                      <h3 id="wf-taxes" className="text-[13px] font-extrabold text-ink-2">
                        Prima dei pilastri
                      </h3>
                      <ol>
                        <TaxRow rung={waterfall.tax_provision} currency={currency} />
                      </ol>
                    </section>
                  )}
                  {groups.map(({ kind, steps: group }) => (
                    <section key={kind} aria-labelledby={`wf-pillar-${kind}`}>
                      <h3 id={`wf-pillar-${kind}`} className="text-[13px] font-extrabold text-ink-2">
                        {PILLAR_OF_KIND[kind].number} · {PILLAR_OF_KIND[kind].title}
                      </h3>
                      <ol>
                        {group.map((step, i) => (
                          <li key={step.goal_id} className="flex items-start gap-1 border-t border-line first:border-t-0">
                            <div className="min-w-0 flex-1">
                              <StepRow step={step} index={i} goal={goalsById.get(step.goal_id)} currency={currency} />
                            </div>
                            <div className="pt-3">
                              <RowMenu
                                label={`Azioni per ${step.name}`}
                                items={[
                                  { label: 'Fonti collegate…', onSelect: () => setEditingSources(goalsById.get(step.goal_id) ?? null) },
                                  ...(i > 0 ? [{ label: 'Più priorità', onSelect: () => move(step.goal_id, -1) }] : []),
                                  ...(i < group.length - 1 ? [{ label: 'Meno priorità', onSelect: () => move(step.goal_id, 1) }] : []),
                                  ...(step.target_mode === 'fixed_amount'
                                    ? [{ label: 'Segna come raggiunto', onSelect: () => patchGoal(step.goal_id, { completed_at: toISODate(new Date()) }) }]
                                    : []),
                                  {
                                    label: 'Elimina obiettivo',
                                    tone: 'danger',
                                    onSelect: () => {
                                      setDeleteError(null)
                                      setDeleting(goalsById.get(step.goal_id) ?? null)
                                    },
                                  },
                                ]}
                              />
                            </div>
                          </li>
                        ))}
                      </ol>
                    </section>
                  ))}
                </div>
              )}
              {goalError && (
                <div className="mt-2">
                  <ErrorBlock>{goalError}</ErrorBlock>
                </div>
              )}
              {completed.length > 0 && (
                <div className="mt-3 border-t border-line pt-3">
                  <h3 className="text-[13px] font-extrabold text-ink-2">Raggiunti</h3>
                  <ul className="mt-1">
                    {completed.map((g) => (
                      <li key={g.id} className="flex items-center justify-between gap-2 py-1 text-[13px]">
                        <span>
                          <b>{g.name}</b> <span className="text-ink-3">il {formatFullDate(g.completed_at as string)}</span>
                        </span>
                        <Button onClick={() => patchGoal(g.id, { completed_at: null })} disabled={updateGoal.isPending}>
                          Riapri
                        </Button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            <section aria-labelledby="wf-actions" className="min-w-0 flex-[1_1_320px]">
              <h3 id="wf-actions" className="text-[14px] font-extrabold">
                Azioni consigliate
              </h3>
              {actions.length === 0 ? (
                <p className="mt-2 text-[13px] text-ink-3">
                  {steps.length === 0 ? 'Le azioni compaiono quando c’è almeno un obiettivo.' : 'Nessuna azione: la quota di questo mese è già al suo posto.'}
                </p>
              ) : (
                <>
                  {waterfall.source_is_fallback && (
                    <p className="mt-1 text-[13px] text-ink-2">
                      Partono da {accounts.find((a) => a.id === waterfall.source_account_id)?.name ?? 'il conto'}{' '}
                      <Tip label="Perché da questo conto">
                        È il conto di spesa con più liquidità: puoi cambiarlo riga per riga, o fissarlo nel piano come conto di accredito.
                      </Tip>
                    </p>
                  )}
                  <ul className="mt-2 flex flex-col gap-2">
                    {actions.map((a) => (
                      <ActionRow
                        key={`${actionKey(a)}-${a.kind}`}
                        action={a}
                        accounts={accounts}
                        choice={choices[actionKey(a)]}
                        onChoose={(c) => setChoices((current) => ({ ...current, [actionKey(a)]: c }))}
                        selected={selected.has(actionKey(a))}
                        onToggle={() => toggle(actionKey(a))}
                      />
                    ))}
                  </ul>
                  {executableActions.length > 0 && (
                    <div className="mt-3 flex flex-col gap-2">
                      <Button variant="primary" onClick={runExecute} disabled={selected.size === 0 || executeWaterfall.isPending}>
                        {executeWaterfall.isPending
                          ? 'Esecuzione…'
                          : `Esegui ${selected.size} ${selected.size === 1 ? 'giroconto' : 'giroconti'}`}
                      </Button>
                      {executeError && <ErrorBlock>{executeError}</ErrorBlock>}
                    </div>
                  )}
                </>
              )}
            </section>
          </div>
        </>
      )}

      <Dialog open={adding} onClose={() => setAdding(false)} title="Nuovo obiettivo" size="md">
        {adding && <GoalForm onDone={() => setAdding(false)} />}
      </Dialog>
      <GoalSourcesDialog goal={editingSources ? (goalsById.get(editingSources.id) ?? null) : null} onClose={() => setEditingSources(null)} />
      <ConfirmDialog
        open={!!deleting}
        title={`Eliminare “${deleting?.name}”?`}
        confirmLabel="Elimina"
        pending={deleteGoal.isPending}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      >
        I conti collegati restano; i giroconti già fatti restano nei movimenti.
      </ConfirmDialog>
    </Card>
  )
}
