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
import {
  useAddGoalSource,
  useCreateGoal,
  useDeleteGoal,
  useExecuteWaterfall,
  useRemoveGoalSource,
  useSavingsGoals,
  useWaterfall,
} from '@/hooks/useSavingsGoals'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatPercent } from '@/lib/format'
import type { SavingsGoal, SavingsGoalKind, TargetMode, WaterfallAction, WaterfallStep } from '@/types'

const KIND_LABELS: Record<SavingsGoalKind, string> = {
  emergency_fund: 'Fondo emergenza',
  medium_term: 'Medio termine',
  long_term: 'Lungo termine',
}

const TARGET_MODE_LABELS: Record<TargetMode, string> = {
  months_of_primary_expenses: 'Mesi di spese primarie',
  fixed_amount: 'Importo fisso',
  open_ended: 'Senza target (assorbe il residuo)',
}

function StepRow({ step, index, goal, currency }: { step: WaterfallStep; index: number; goal?: SavingsGoal; currency: string }) {
  const { data: accounts } = useAccounts()
  const sources = (goal?.sources ?? []).map((s) => accounts?.find((a) => a.id === s.account_id)?.name).filter(Boolean)
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
            <span className="sr-only">Gradino {index + 1}: </span>
            {step.name} <span className="text-[12px] font-semibold text-ink-3">{KIND_LABELS[step.kind]}</span>
          </span>
          <span className="flex flex-wrap gap-1.5">
            {Number(step.allocated_amount) > 0 && <StatusChip kind="info">+{money(step.allocated_amount)} da versare</StatusChip>}
            {step.is_funded && <StatusChip kind="good">Completo</StatusChip>}
          </span>
        </div>
        {step.target_unavailable ? (
          <p className="mt-1 text-[13px] font-semibold text-warn">
            Target non ancora calcolabile: serve almeno un mese completo di storico per la media delle spese primarie. Il gradino è sospeso, non
            considerato completo.
          </p>
        ) : step.target_amount === null ? (
          <p className="mt-1 text-[13px] text-ink-2">Senza target: riceve tutto ciò che avanza dai gradini sopra. Ora {money(step.current_amount)}.</p>
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
        <p className="mt-1 text-[12px] text-ink-3">{sources.length ? `Conti: ${sources.join(', ')}` : 'Nessun conto collegato'}</p>
      </div>
    </div>
  )
}

function ActionRow({ action, selected, onToggle }: { action: WaterfallAction; selected: boolean; onToggle: () => void }) {
  const executable = action.kind === 'transfer'
  const money = `${formatAmount(action.amount, action.currency)} ${action.currency}`
  return (
    <li className={`rounded-[10px] border px-3 py-2.5 ${executable ? 'border-line bg-card' : 'border-dashed border-field bg-card-2'}`}>
      <label className={`flex items-start gap-3 ${executable ? 'cursor-pointer' : ''}`}>
        {executable ? (
          <input type="checkbox" checked={selected} onChange={onToggle} className="mt-1 h-[18px] w-[18px] flex-none accent-accent" />
        ) : (
          <span aria-hidden="true" className="mt-0.5 w-[18px] flex-none text-center text-ink-3">
            ✎
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-bold tabular-nums">
              {executable ? (
                <>
                  ⇄ Gira {money} da {action.from_account_name} a {action.to_account_name}
                </>
              ) : (
                <>
                  {money} verso «{action.goal_name}»
                </>
              )}
            </span>
            <StatusChip kind={executable ? 'info' : 'ok'}>{executable ? 'Giroconto' : 'Da fare a mano'}</StatusChip>
          </span>
          <span className="mt-0.5 block text-[13px] text-ink-2">{action.reason}</span>
        </span>
      </label>
    </li>
  )
}

function GoalForm({ nextPriority, onDone }: { nextPriority: number; onDone: () => void }) {
  const createGoal = useCreateGoal()
  const [name, setName] = useState('')
  const [kind, setKind] = useState<SavingsGoalKind>('emergency_fund')
  const [targetMode, setTargetMode] = useState<TargetMode>('months_of_primary_expenses')
  const [months, setMonths] = useState('6')
  const [amount, setAmount] = useState('')
  const [priority, setPriority] = useState(String(nextPriority))
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    if (!name.trim()) return setError('Il nome è obbligatorio')
    try {
      await createGoal.mutateAsync({
        name: name.trim(),
        kind,
        priority: Number(priority),
        target_mode: targetMode,
        target_months: targetMode === 'months_of_primary_expenses' ? months : null,
        target_amount: targetMode === 'fixed_amount' ? amount.replace(',', '.') : null,
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
        <Field label="Tipo" htmlFor="goal-kind">
          <select id="goal-kind" className="field" value={kind} onChange={(e) => setKind(e.target.value as SavingsGoalKind)}>
            {(Object.keys(KIND_LABELS) as SavingsGoalKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Target" htmlFor="goal-mode">
          <select id="goal-mode" className="field" value={targetMode} onChange={(e) => setTargetMode(e.target.value as TargetMode)}>
            {(Object.keys(TARGET_MODE_LABELS) as TargetMode[]).map((m) => (
              <option key={m} value={m}>
                {TARGET_MODE_LABELS[m]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Priorità" htmlFor="goal-priority" hint="Più bassa = riempita prima.">
          <input id="goal-priority" type="number" min={0} className="field" aria-describedby="goal-priority-msg" value={priority} onChange={(e) => setPriority(e.target.value)} />
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

function GoalSourcesDialog({ goal, onClose }: { goal: SavingsGoal | null; onClose: () => void }) {
  const { data: accounts } = useAccounts()
  const addSource = useAddGoalSource()
  const removeSource = useRemoveGoalSource()
  const [accountId, setAccountId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const linked = new Set(goal?.sources.map((s) => s.account_id))

  async function add() {
    if (!goal || !accountId) return
    setError(null)
    try {
      await addSource.mutateAsync({ goalId: goal.id, accountId })
      setAccountId('')
    } catch (e) {
      // 409 when the account already funds another goal.
      setError(apiErrorMessage(e, 'Impossibile collegare il conto.'))
    }
  }

  return (
    <Dialog
      open={!!goal}
      onClose={onClose}
      title={`Conti di “${goal?.name ?? ''}”`}
      description="Il saldo di questi conti conta come quanto già accantonato. Un conto può finanziare un solo obiettivo."
    >
      {goal && (
        <div className="flex flex-col gap-3">
          {goal.sources.length === 0 ? (
            <p className="text-[14px] text-ink-3">Nessun conto collegato.</p>
          ) : (
            <ul>
              {goal.sources.map((source) => (
                <li key={source.id} className="flex items-center justify-between border-t border-line py-1 first:border-t-0">
                  <span className="font-semibold">{accounts?.find((a) => a.id === source.account_id)?.name ?? 'Conto eliminato'}</span>
                  <button
                    type="button"
                    onClick={() => removeSource.mutateAsync({ goalId: goal.id, sourceId: source.id })}
                    disabled={removeSource.isPending}
                    aria-label="Scollega il conto"
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
              Conto da collegare
            </label>
            <select id="goal-source" className="field min-w-0 flex-1" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">Collega un conto…</option>
              {(accounts ?? [])
                .filter((a) => !linked.has(a.id) && !a.closed_at)
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} · {a.currency}
                  </option>
                ))}
            </select>
            <Button variant="primary" onClick={add} disabled={!accountId || addSource.isPending}>
              Collega
            </Button>
          </div>
          {error && <ErrorBlock>{error}</ErrorBlock>}
        </div>
      )}
    </Dialog>
  )
}

/**
 * The savings ladder: the month's savings quota fills goals in priority
 * order and spills to the next rung only when the one above is full.
 * Suggested giroconti are pre-selected and run as one all-or-nothing batch.
 */
export function WaterfallSection({ date, currency }: { date: string; currency: string }) {
  const { data: waterfall, isLoading, isError } = useWaterfall(date)
  const { data: goals } = useSavingsGoals()
  const deleteGoal = useDeleteGoal()
  const executeWaterfall = useExecuteWaterfall()
  const [adding, setAdding] = useState(false)
  const [editingSources, setEditingSources] = useState<SavingsGoal | null>(null)
  const [deleting, setDeleting] = useState<SavingsGoal | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deselected, setDeselected] = useState<Set<string>>(new Set())
  const [executeError, setExecuteError] = useState<string | null>(null)

  const goalsById = new Map((goals ?? []).map((g) => [g.id, g]))
  const actions = waterfall?.actions ?? []
  const executableActions = actions.filter((a) => a.kind === 'transfer')
  // Selected by default — acting on the suggestions is the common case.
  // Tracking the opt-outs keeps the set right when the cascade recomputes.
  const selected = new Set(executableActions.map((a) => a.goal_id).filter((id) => !deselected.has(id)))

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
      .filter((a) => selected.has(a.goal_id))
      .map((a) => ({ goal_id: a.goal_id, from_account_id: a.from_account_id as string, amount: a.amount }))
    if (items.length === 0) return
    try {
      await executeWaterfall.mutateAsync({ date, items })
      setDeselected(new Set())
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

  const steps = [...(waterfall?.steps ?? [])].sort((a, b) => a.priority - b.priority)
  const nextPriority = steps.length ? Math.max(...steps.map((s) => s.priority)) + 1 : 0

  return (
    <Card
      title="Cascata del risparmio"
      action={
        <Button variant="secondary" onClick={() => setAdding(true)}>
          + Nuovo obiettivo
        </Button>
      }
    >
      <p className="mt-1 text-[13px] text-ink-2">
        La quota di risparmio riempie gli obiettivi in ordine di priorità: si passa al gradino dopo solo quando il precedente è pieno (al 95%).
      </p>

      {isLoading ? (
        <LoadingBlock className="mt-3 h-40" />
      ) : isError || !waterfall ? (
        <div className="mt-3">
          <ErrorBlock>Non è stato possibile calcolare la cascata.</ErrorBlock>
        </div>
      ) : (
        <>
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px] tabular-nums">
            {[
              ['Quota di risparmio', waterfall.savings_quota],
              ['Già allocato', waterfall.already_allocated],
              ['Da allocare', waterfall.unallocated_amount],
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
                <ol aria-label="Gradini">
                  {steps.map((step, i) => (
                    <li key={step.goal_id} className="flex items-start gap-1 border-t border-line first:border-t-0">
                      <div className="min-w-0 flex-1">
                        <StepRow step={step} index={i} goal={goalsById.get(step.goal_id)} currency={currency} />
                      </div>
                      <div className="pt-3">
                        <RowMenu
                          label={`Azioni per ${step.name}`}
                          items={[
                            { label: 'Conti collegati…', onSelect: () => setEditingSources(goalsById.get(step.goal_id) ?? null) },
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
                  <ul className="mt-2 flex flex-col gap-2">
                    {actions.map((a) => (
                      <ActionRow key={`${a.goal_id}-${a.kind}`} action={a} selected={selected.has(a.goal_id)} onToggle={() => toggle(a.goal_id)} />
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
        {adding && <GoalForm nextPriority={nextPriority} onDone={() => setAdding(false)} />}
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
