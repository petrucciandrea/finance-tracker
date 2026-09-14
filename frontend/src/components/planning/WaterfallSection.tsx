import { useState } from 'react'
import { isAxiosError } from 'axios'
import { TrashIcon } from '@/components/ui/Icon'
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
import type {
  ApiErrorResponse,
  SavingsGoal,
  SavingsGoalKind,
  TargetMode,
  WaterfallAction,
  WaterfallStep,
} from '@/types'

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

function apiMessage(error: unknown, fallback: string): string {
  if (isAxiosError<ApiErrorResponse>(error) && error.response) {
    return error.response.data?.error?.message ?? fallback
  }
  return fallback
}

function StepRow({
  step,
  format,
}: {
  step: WaterfallStep
  format: (amount: string | null) => string
}) {
  const width = Math.min(Math.max(step.funding_percentage, 0), 100)

  return (
    <li className="py-3">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium text-slate-800">
          {step.name} <span className="text-xs text-slate-400">{KIND_LABELS[step.kind]}</span>
        </span>
        {Number(step.allocated_amount) > 0 && (
          <span className="shrink-0 rounded bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
            +{format(step.allocated_amount)}
          </span>
        )}
      </div>

      {step.target_unavailable ? (
        <p className="mt-1 text-xs text-amber-700">
          Target non ancora calcolabile: serve almeno un mese completo di storico per la media
          delle spese primarie. Il gradino è sospeso, non considerato completo.
        </p>
      ) : step.target_amount === null ? (
        <p className="mt-1 text-xs text-slate-500">
          Nessun target — riceve tutto ciò che avanza dai gradini sopra. Attuale{' '}
          {format(step.current_amount)}.
        </p>
      ) : (
        <>
          <div className="mt-1 flex justify-between text-xs text-slate-500">
            <span>
              {format(step.current_amount)} / {format(step.target_amount)}
            </span>
            <span>{step.funding_percentage}%</span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full ${step.is_funded ? 'bg-green-600' : 'bg-slate-800'}`}
              style={{ width: `${width}%` }}
            />
          </div>
        </>
      )}
    </li>
  )
}

function ActionRow({
  action,
  format,
  selected,
  onToggle,
}: {
  action: WaterfallAction
  format: (amount: string | null) => string
  selected: boolean
  onToggle: () => void
}) {
  const executable = action.kind === 'transfer'

  return (
    <li
      className={`rounded-md border px-3 py-2 text-sm ${
        executable ? 'border-slate-200 bg-white' : 'border-dashed border-slate-300 bg-slate-50'
      }`}
    >
      <div className="flex items-baseline justify-between gap-3">
        {executable && (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={`Seleziona il giroconto verso ${action.goal_name}`}
            className="mt-1 shrink-0 rounded border-slate-300 text-slate-800 focus:ring-slate-500"
          />
        )}
        <span className="flex-1 font-medium text-slate-800">
          {executable ? (
            <>
              Gira {format(action.amount)} da {action.from_account_name} a{' '}
              {action.to_account_name}
            </>
          ) : (
            <>
              {format(action.amount)} verso «{action.goal_name}»
            </>
          )}
        </span>
        <span
          className={`shrink-0 rounded px-2 py-0.5 text-xs ${
            executable ? 'bg-slate-800 text-white' : 'bg-slate-200 text-slate-600'
          }`}
        >
          {executable ? 'Giroconto' : 'Da fare a mano'}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-slate-500">{action.reason}</p>
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
  const [priority, setPriority] = useState('0')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    try {
      await createGoal.mutateAsync({
        name: name.trim(),
        kind,
        priority: Number(priority),
        target_mode: targetMode,
        // Each mode carries exactly its own parameter — the backend 422s
        // anything else, and the database constrains it too.
        target_months: targetMode === 'months_of_primary_expenses' ? months : null,
        target_amount: targetMode === 'fixed_amount' ? amount : null,
      })
      onDone()
    } catch (e) {
      setError(apiMessage(e, 'Impossibile creare il gradino.'))
    }
  }

  return (
    <div className="space-y-3 rounded-md bg-slate-50 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="goal-name" className="block text-xs font-medium text-slate-600">
            Nome
          </label>
          <input
            id="goal-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label htmlFor="goal-kind" className="block text-xs font-medium text-slate-600">
            Tipo
          </label>
          <select
            id="goal-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as SavingsGoalKind)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {(Object.keys(KIND_LABELS) as SavingsGoalKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="goal-mode" className="block text-xs font-medium text-slate-600">
            Target
          </label>
          <select
            id="goal-mode"
            value={targetMode}
            onChange={(e) => setTargetMode(e.target.value as TargetMode)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {(Object.keys(TARGET_MODE_LABELS) as TargetMode[]).map((m) => (
              <option key={m} value={m}>
                {TARGET_MODE_LABELS[m]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="goal-priority" className="block text-xs font-medium text-slate-600">
            Priorità (0 = primo)
          </label>
          <input
            id="goal-priority"
            type="number"
            min={0}
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        {targetMode === 'months_of_primary_expenses' && (
          <div>
            <label htmlFor="goal-months" className="block text-xs font-medium text-slate-600">
              Mesi di spese primarie
            </label>
            <input
              id="goal-months"
              type="number"
              min={1}
              value={months}
              onChange={(e) => setMonths(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
        )}
        {targetMode === 'fixed_amount' && (
          <div>
            <label htmlFor="goal-amount" className="block text-xs font-medium text-slate-600">
              Importo obiettivo
            </label>
            <input
              id="goal-amount"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
        )}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <button
        onClick={submit}
        disabled={createGoal.isPending || !name.trim()}
        className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {createGoal.isPending ? 'Creazione...' : 'Aggiungi gradino'}
      </button>
    </div>
  )
}

function GoalSources({ goal }: { goal: SavingsGoal }) {
  const { data: accounts } = useAccounts()
  const addSource = useAddGoalSource()
  const removeSource = useRemoveGoalSource()
  const [accountId, setAccountId] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mappedIds = new Set(goal.sources.map((s) => s.account_id))
  const available = (accounts ?? []).filter((a) => !mappedIds.has(a.id))

  async function attach() {
    if (!accountId) return
    setError(null)
    try {
      await addSource.mutateAsync({ goalId: goal.id, accountId })
      setAccountId('')
    } catch (e) {
      // Most likely a 409: the account already funds another goal.
      setError(apiMessage(e, 'Impossibile collegare il conto.'))
    }
  }

  return (
    <div className="mt-2 pl-4">
      <ul className="space-y-1">
        {goal.sources.map((source) => {
          const account = accounts?.find((a) => a.id === source.account_id)
          return (
            <li
              key={source.id}
              className="flex items-center justify-between text-xs text-slate-600"
            >
              <span>{account?.name ?? 'Conto eliminato'}</span>
              <button
                onClick={() => removeSource.mutateAsync({ goalId: goal.id, sourceId: source.id })}
                aria-label="Scollega"
                title="Scollega"
                className="rounded p-1 text-red-600 hover:bg-red-50"
              >
                <TrashIcon />
              </button>
            </li>
          )
        })}
      </ul>

      <div className="mt-2 flex gap-2">
        <select
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          aria-label={`Collega un conto a ${goal.name}`}
          className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs"
        >
          <option value="">Collega un conto...</option>
          {available.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <button
          onClick={attach}
          disabled={!accountId || addSource.isPending}
          className="rounded-md bg-slate-200 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-300 disabled:opacity-50"
        >
          Collega
        </button>
      </div>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

export function WaterfallSection({ format }: { format: (amount: string | null) => string }) {
  const { data: waterfall, isLoading } = useWaterfall()
  const { data: goals } = useSavingsGoals()
  const deleteGoal = useDeleteGoal()
  const executeWaterfall = useExecuteWaterfall()
  const [isAdding, setIsAdding] = useState(false)
  const [deselected, setDeselected] = useState<Set<string>>(new Set())
  const [executeError, setExecuteError] = useState<string | null>(null)

  const executableActions = (waterfall?.actions ?? []).filter((a) => a.kind === 'transfer')
  // Selected by default — the suggestions are the point of the page, so
  // acting on all of them is the common case and opting out is the
  // exception. Tracking the exceptions keeps the set correct when the
  // cascade is recomputed after a transfer lands.
  const selected = new Set(
    executableActions.map((a) => a.goal_id).filter((id) => !deselected.has(id)),
  )

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
      .map((a) => ({
        goal_id: a.goal_id,
        from_account_id: a.from_account_id as string,
        amount: a.amount,
      }))
    if (items.length === 0) return

    try {
      await executeWaterfall.mutateAsync({ items })
      setDeselected(new Set())
    } catch (e) {
      // The backend applies the batch all-or-nothing, so nothing landed.
      setExecuteError(apiMessage(e, 'Impossibile eseguire i giroconti.'))
    }
  }

  if (isLoading) return <p className="text-slate-500">Caricamento...</p>

  return (
    <div className="space-y-5">
      {waterfall && (
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span className="text-slate-600">
            Quota risparmio: <strong>{format(waterfall.savings_quota)}</strong>
          </span>
          <span className="text-slate-600">
            Già allocato: <strong>{format(waterfall.already_allocated)}</strong>
          </span>
          <span className="text-slate-600">
            Non allocato: <strong>{format(waterfall.unallocated_amount)}</strong>
          </span>
        </div>
      )}

      {waterfall && waterfall.steps.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {waterfall.steps.map((step) => (
            <StepRow key={step.goal_id} step={step} format={format} />
          ))}
        </ul>
      )}

      {waterfall && waterfall.actions.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-700">Azioni consigliate</h3>
          <ul className="space-y-2">
            {waterfall.actions.map((action) => (
              <ActionRow
                key={action.goal_id}
                action={action}
                format={format}
                selected={selected.has(action.goal_id)}
                onToggle={() => toggle(action.goal_id)}
              />
            ))}
          </ul>

          {executableActions.length > 0 && (
            <div className="mt-3 flex items-center gap-3">
              <button
                onClick={runExecute}
                disabled={selected.size === 0 || executeWaterfall.isPending}
                className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                {executeWaterfall.isPending
                  ? 'Esecuzione...'
                  : `Esegui ${selected.size} giroconto${selected.size === 1 ? '' : 'i'}`}
              </button>
              {executeError && <p className="text-sm text-red-600">{executeError}</p>}
            </div>
          )}
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-700">Gradini e conti collegati</h3>
        {(goals ?? []).length === 0 && (
          <p className="text-sm text-slate-500">
            Nessun gradino ancora. Il primo è di solito un fondo emergenza da 6 mesi di spese
            primarie.
          </p>
        )}
        <ul className="space-y-3">
          {(goals ?? []).map((goal) => (
            <li key={goal.id} className="rounded-md border border-slate-200 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-800">
                  {goal.priority}. {goal.name}
                </span>
                <button
                  onClick={() => {
                    if (window.confirm(`Eliminare il gradino "${goal.name}"?`)) {
                      deleteGoal.mutateAsync(goal.id)
                    }
                  }}
                  aria-label="Elimina gradino"
                  title="Elimina gradino"
                  className="rounded p-1.5 text-red-600 hover:bg-red-50"
                >
                  <TrashIcon />
                </button>
              </div>
              <GoalSources goal={goal} />
            </li>
          ))}
        </ul>
      </div>

      <div>
        <button
          onClick={() => setIsAdding((v) => !v)}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          {isAdding ? 'Annulla' : 'Nuovo gradino'}
        </button>
        {isAdding && (
          <div className="mt-3">
            <GoalForm onDone={() => setIsAdding(false)} />
          </div>
        )}
      </div>
    </div>
  )
}
