import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog'
import { ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { RowMenu } from '@/components/ui/RowMenu'
import { StatusChip } from '@/components/ui/StatusChip'
import { ActionRow, GoalForm, GoalSourcesDialog, StepRow, TaxRow } from '@/components/planning/GoalRows'
import { Tip } from '@/components/ui/Tip'
import { useAccounts } from '@/hooks/useAccounts'
import { usePlan, useUpdatePlan } from '@/hooks/usePlanning'
import { useDeleteGoal, useExecuteWaterfall, usePillars, useSavingsGoals, useUpdateGoal, useWaterfall } from '@/hooks/useSavingsGoals'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatFullDate, formatShortDate, toISODate, toNumber } from '@/lib/format'
import { PILLAR_TITLES } from '@/lib/goals'
import { actionKey, resolve, type Choice } from '@/lib/waterfallActions'
import type { Pillar, PillarItem, PillarKey, SavingsGoal, SavingsGoalKind, WaterfallAction, WaterfallPlan } from '@/types'

const PILLARS: Record<PillarKey, { title: string; blurb: string; kind: SavingsGoalKind | null }> = {
  operating: {
    title: PILLAR_TITLES.operating,
    blurb: 'I conti per le spese del mese, non assegnati a obiettivi. Quello che hanno in più scende ai pilastri successivi.',
    kind: null,
  },
  emergency: { title: PILLAR_TITLES.emergency, blurb: 'La riserva per gli imprevisti: si riempie per prima, subito dopo le tasse.', kind: 'emergency_fund' },
  planned: { title: PILLAR_TITLES.planned, blurb: 'Spese con una data o già note: auto, casa, tasse, scadenze.', kind: 'medium_term' },
  investing: { title: PILLAR_TITLES.investing, blurb: 'Il lungo periodo: quello che non serve nei prossimi anni.', kind: 'long_term' },
}

const MONTH_CHOICES = ['0.5', '1', '2', '3']

function money(value: string | null, currency: string) {
  return `${formatAmount(value, currency)} ${currency}`
}

function ItemRow({ item }: { item: PillarItem }) {
  const detail =
    item.kind === 'vehicle_deadline' && item.due_date
      ? `${money(item.amount, item.currency)} entro il ${formatShortDate(item.due_date)} · ${money(item.monthly, item.currency)}/mese`
      : item.kind === 'tax_provision'
        ? `${money(item.available, item.currency)} su ${money(item.amount, item.currency)} che chiederanno gli F24`
        : money(item.available, item.currency)
  return (
    <li className="flex flex-col py-1 text-[13px]">
      <span className="font-semibold">{item.label}</span>
      <span className="text-ink-2 tabular-nums">{detail}</span>
    </li>
  )
}

function OperatingMonths({ value }: { value: string }) {
  const { data: plan } = usePlan()
  const updatePlan = useUpdatePlan()
  const current = String(Number(plan?.operating_cash_months ?? value))
  return (
    <label className="flex flex-wrap items-center gap-2 text-[13px] text-ink-2">
      Obiettivo
      <select
        className="field h-9 w-auto py-0"
        value={current}
        disabled={updatePlan.isPending}
        onChange={(e) => updatePlan.mutate({ operating_cash_months: e.target.value })}
      >
        {MONTH_CHOICES.map((m) => (
          <option key={m} value={m}>
            {m.replace('.', ',')} {m === '1' ? 'mese' : 'mesi'}
          </option>
        ))}
      </select>
      di spese medie
    </label>
  )
}

function PillarNumbers({ pillar, currency }: { pillar: Pillar; currency: string }) {
  const meta = PILLARS[pillar.key]
  const target = pillar.target === null ? null : toNumber(pillar.target)
  const pct = target ? Math.min(100, (toNumber(pillar.current) / target) * 100) : null
  const full = target !== null && toNumber(pillar.gap) <= 0
  return (
    <>
      <p className="text-[20px] font-extrabold tabular-nums">
        {formatAmount(pillar.current, currency)} <span className="ccy text-[13px]">{currency}</span>
      </p>
      {target !== null ? (
        <>
          <p className="text-[13px] text-ink-2 tabular-nums">
            su {money(pillar.target, currency)}
            {!full && <> · mancano {money(pillar.gap, currency)}</>}
          </p>
          <div className="mt-1.5">
            <ProgressBar value={pct ?? 0} kind={full ? 'good' : 'ok'} label={`${meta.title}: ${Math.round(pct ?? 0)}%`} />
          </div>
        </>
      ) : pillar.key === 'operating' ? (
        <p className="text-[13px] text-warn">Obiettivo da calcolare: serve un mese completo di spese.</p>
      ) : pillar.key === 'investing' ? (
        <p className="text-[13px] text-ink-2">Senza tetto: è dove va ciò che avanza.</p>
      ) : (
        <p className="text-[13px] text-ink-3">Nessun obiettivo.</p>
      )}
      {pillar.monthly_required !== null && toNumber(pillar.monthly_required) > 0 && (
        <p className="mt-1 text-[13px] font-semibold tabular-nums">{money(pillar.monthly_required, currency)} al mese da mettere da parte</p>
      )}
    </>
  )
}

function DistributionSummary({ waterfall, currency }: { waterfall: WaterfallPlan; currency: string }) {
  const rows: [string, string][] = [['Quota di risparmio', waterfall.savings_quota]]
  if (waterfall.operating_surplus !== null) rows.push(['Eccedenza sui conti di spesa', waterfall.operating_surplus])
  if (toNumber(waterfall.goal_account_excess) > 0) rows.push(['Eccedenza sui conti obiettivo', waterfall.goal_account_excess])
  rows.push(['Da distribuire', waterfall.budget], ['Già versato', waterfall.already_allocated], ['Avanzo', waterfall.unallocated_amount])
  return (
    <dl aria-label="Da distribuire questo mese" className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px] tabular-nums">
      {rows.map(([label, value]) => (
        <div key={label} className="flex gap-1.5">
          <dt className="text-ink-2">{label}</dt>
          <dd className="font-extrabold">
            {formatAmount(value, currency)} <span className="ccy">{currency}</span>
          </dd>
        </div>
      ))}
    </dl>
  )
}

interface ActionListProps {
  actions: WaterfallAction[]
  choices: Record<string, Choice>
  onChoose: (key: string, choice: Choice) => void
  selected: Set<string>
  onToggle: (key: string) => void
}

function ActionList({ actions, choices, onChoose, selected, onToggle }: ActionListProps) {
  const { data: accountList } = useAccounts()
  if (actions.length === 0) return null
  return (
    <ul aria-label="Giroconti suggeriti" className="mb-3 flex flex-col gap-2 sm:ml-11">
      {actions.map((a) => (
        <ActionRow
          key={`${actionKey(a)}-${a.kind}`}
          action={a}
          accounts={accountList ?? []}
          choice={choices[actionKey(a)]}
          onChoose={(c) => onChoose(actionKey(a), c)}
          selected={selected.has(actionKey(a))}
          onToggle={() => onToggle(actionKey(a))}
        />
      ))}
    </ul>
  )
}

/**
 * The plan in one place: the four pillars in the order money fills them,
 * each with its goals and, under each goal, the giroconti this month
 * suggests for it. The tax provision is served before every pillar (it is a
 * debt) though it is counted in pillar 3. Suggestions are pre-selected and
 * run as one all-or-nothing batch.
 */
export function PillarsSection({ date }: { date: string }) {
  const { data, isLoading, isError } = usePillars(date)
  const { data: waterfall } = useWaterfall(date)
  const { data: goals } = useSavingsGoals()
  const { data: accountList } = useAccounts()
  const accounts = accountList ?? []
  const deleteGoal = useDeleteGoal()
  const updateGoal = useUpdateGoal()
  const executeWaterfall = useExecuteWaterfall()

  const [adding, setAdding] = useState<SavingsGoalKind | null>(null)
  const [editingSources, setEditingSources] = useState<SavingsGoal | null>(null)
  const [deleting, setDeleting] = useState<SavingsGoal | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [goalError, setGoalError] = useState<string | null>(null)
  const [executeError, setExecuteError] = useState<string | null>(null)
  // The user's per-row picks (source, and destination for a goal with no
  // account) and opt-outs, keyed by actionKey. Lost on reload, on purpose:
  // the suggestions may have moved.
  const [choices, setChoices] = useState<Record<string, Choice>>({})
  const [deselected, setDeselected] = useState<Set<string>>(new Set())

  const goalsById = new Map((goals ?? []).map((g) => [g.id, g]))
  const completed = (goals ?? []).filter((g) => g.completed_at)
  // Already in the server's order: pillar, then priority inside it.
  const steps = waterfall?.steps ?? []
  const actions = waterfall?.actions ?? []
  const executableActions = actions.filter((a) => resolve(a, choices[actionKey(a)], accounts).executable)
  // Selected by default — acting on the suggestions is the common case.
  // Tracking the opt-outs keeps the set right when the suggestions recompute.
  const selected = new Set(executableActions.map(actionKey).filter((id) => !deselected.has(id)))
  const actionsFor = (goalId: string | null) =>
    actions.filter((a) => (goalId === null ? a.purpose === 'tax_provision' : a.goal_id === goalId))

  function toggle(key: string) {
    setDeselected((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
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

  const actionProps = {
    choices,
    onChoose: (key: string, c: Choice) => setChoices((current) => ({ ...current, [key]: c })),
    selected,
    onToggle: toggle,
  }

  function renderPillar(pillar: Pillar, index: number, currency: string) {
    const meta = PILLARS[pillar.key]
    const full = pillar.target !== null && toNumber(pillar.gap) <= 0
    const behind = pillar.steps.filter((s) => s.on_track === false).length
    const group = meta.kind === null ? [] : steps.filter((s) => s.kind === meta.kind)
    // Pillar 3 counts the tax provision; when the month has a rung for it, it
    // is shown as that rung (with its giroconto) rather than as a plain item.
    const taxRung = pillar.key === 'planned' ? (waterfall?.tax_provision ?? null) : null
    const items = pillar.items.filter((i) => !(taxRung && i.kind === 'tax_provision'))
    const hasRows = group.length > 0 || items.length > 0 || taxRung !== null
    const headingId = `pillar-${pillar.key}`

    return (
      <section key={pillar.key} aria-labelledby={headingId} className="rounded-[12px] border border-line bg-card-2/40 p-3">
        <div className="flex flex-wrap gap-x-6 gap-y-3">
          <div className="min-w-0 flex-[1_1_220px]">
            <div className="flex items-baseline justify-between gap-2">
              <h3 id={headingId} className="text-[15px] font-extrabold">
                <span className="text-ink-3">{index + 1}</span> {meta.title}
              </h3>
              {full ? <StatusChip kind="good">Coperto</StatusChip> : behind > 0 ? <StatusChip kind="over">{behind} in ritardo</StatusChip> : null}
            </div>
            <p className="mb-2 text-[12px] text-ink-3">{meta.blurb}</p>
            <PillarNumbers pillar={pillar} currency={currency} />
            {pillar.key === 'operating' && data && (
              <div className="mt-2">
                <OperatingMonths value={data.operating_cash_months} />
                {data.monthly_total_expenses !== null && (
                  <p className="text-[12px] text-ink-3 tabular-nums">Spesa media: {money(data.monthly_total_expenses, currency)} al mese</p>
                )}
              </div>
            )}
          </div>

          <div className="min-w-0 flex-[2_1_380px]">
            {taxRung && (
              <div className={group.length > 0 ? 'border-b border-line' : ''}>
                <ol aria-label="Accantonamento tasse, servito prima di tutti i pilastri">
                  <TaxRow rung={taxRung} currency={currency} />
                </ol>
                <ActionList actions={actionsFor(null)} {...actionProps} />
              </div>
            )}

            {group.length > 0 && (
              <ol aria-label={`Obiettivi di ${meta.title}, in ordine di priorità`}>
                {group.map((step, i) => (
                  <li key={step.goal_id} className="border-t border-line first:border-t-0">
                    <div className="flex items-start gap-1">
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
                    </div>
                    <ActionList actions={actionsFor(step.goal_id)} {...actionProps} />
                  </li>
                ))}
              </ol>
            )}

            {items.length > 0 && (
              <section
                aria-label={pillar.key === 'investing' ? 'Fuori dagli obiettivi' : 'Altre voci'}
                className={group.length > 0 || taxRung ? 'mt-2 border-t border-line pt-2' : ''}
              >
                <h4 className="text-[13px] font-extrabold text-ink-2">
                  {pillar.key === 'investing'
                    ? 'Fuori dagli obiettivi'
                    : pillar.key === 'operating'
                      ? 'Eccedenza sui conti degli obiettivi (già pieni): scende ai pilastri successivi'
                      : 'Già messo da parte o in arrivo'}
                </h4>
                <ul className="mt-1">
                  {items.map((item) => (
                    <ItemRow key={`${item.kind}-${item.label}`} item={item} />
                  ))}
                </ul>
              </section>
            )}

            {meta.kind !== null && (
              <div className={hasRows ? 'mt-2' : ''}>
                {!hasRows && (
                  <p className="text-[13px] text-ink-3">
                    {pillar.key === 'emergency' ? 'Parti da un fondo emergenza di qualche mese di spese primarie.' : 'Nessun obiettivo in questo pilastro.'}
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => setAdding(meta.kind)}
                  className="mt-1 min-h-[44px] cursor-pointer text-[13px] font-bold text-accent hover:underline"
                >
                  + Aggiungi un obiettivo
                </button>
              </div>
            )}
          </div>
        </div>
      </section>
    )
  }

  return (
    <Card
      title="I quattro pilastri"
      meta={
        <Tip>
          <span>
            Prima la liquidità per il mese. Quello che c’è in più, o la quota di risparmio del mese se è di più, va alle tasse, poi al fondo
            emergenza, agli accantonamenti e solo alla fine agli investimenti.
          </span>
          <span>
            Dentro ogni pilastro gli obiettivi seguono la loro priorità, e si passa al successivo solo quando quello sopra è pieno (al 95%). Gli
            obiettivi con una scadenza entrano in ordine di data; dal menu puoi cambiarne la priorità.
          </span>
        </Tip>
      }
    >
      {isLoading ? (
        <LoadingBlock className="mt-3 h-48" />
      ) : isError || !data ? (
        <div className="mt-3">
          <ErrorBlock>Non è stato possibile calcolare i pilastri.</ErrorBlock>
        </div>
      ) : (
        <>
          {waterfall && <DistributionSummary waterfall={waterfall} currency={data.base_currency} />}
          {data.has_unpriced_holdings && (
            <div className="mt-3">
              <Notice>Alcuni investimenti non hanno ancora un prezzo salvato e non sono contati: apri il Portafoglio per aggiornarli.</Notice>
            </div>
          )}

          <div className="mt-3 flex flex-col gap-3">{data.pillars.map((pillar, i) => renderPillar(pillar, i, data.base_currency))}</div>

          {goalError && (
            <div className="mt-2">
              <ErrorBlock>{goalError}</ErrorBlock>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
            {actions.length === 0 ? (
              <p className="text-[13px] text-ink-3">
                {steps.length === 0 ? 'I giroconti compaiono quando c’è almeno un obiettivo.' : 'Nessun giroconto da fare: la quota di questo mese è già al suo posto.'}
              </p>
            ) : (
              <p className="text-[13px] text-ink-2">
                {waterfall?.source_is_fallback ? (
                  <>
                    I giroconti partono da {accounts.find((a) => a.id === waterfall.source_account_id)?.name ?? 'il conto'}{' '}
                    <Tip label="Perché da questo conto">
                      È il conto di spesa con più liquidità: puoi cambiarlo riga per riga, o fissarlo nel piano come conto di accredito.
                    </Tip>
                  </>
                ) : (
                  'I giroconti suggeriti sono sotto ogni obiettivo.'
                )}
              </p>
            )}
            {executableActions.length > 0 && (
              <Button variant="primary" onClick={runExecute} disabled={selected.size === 0 || executeWaterfall.isPending}>
                {executeWaterfall.isPending ? 'Esecuzione…' : `Esegui ${selected.size} ${selected.size === 1 ? 'giroconto' : 'giroconti'}`}
              </Button>
            )}
          </div>
          {executeError && (
            <div className="mt-2">
              <ErrorBlock>{executeError}</ErrorBlock>
            </div>
          )}

          {completed.length > 0 && (
            <div className="mt-3 border-t border-line pt-3">
              <h3 className="text-[13px] font-extrabold text-ink-2">Obiettivi raggiunti</h3>
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
        </>
      )}

      <Dialog open={adding !== null} onClose={() => setAdding(null)} title="Nuovo obiettivo" size="md">
        {adding !== null && <GoalForm initialKind={adding} onDone={() => setAdding(null)} />}
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
