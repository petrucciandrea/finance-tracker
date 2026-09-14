import { useState } from 'react'
import { isAxiosError } from 'axios'
import { WaterfallSection } from '@/components/planning/WaterfallSection'
import { useAuth } from '@/context/AuthContext'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import {
  useAllocationStatus,
  usePlan,
  useSimulate,
  useSurvivalBudget,
  useUpdatePlan,
} from '@/hooks/usePlanning'
import type {
  AllocationBucket,
  AllocationBucketStatus,
  ApiErrorResponse,
  NecessityLevel,
  SimulationCut,
} from '@/types'

const BUCKET_LABELS: Record<AllocationBucket, string> = {
  primary: 'Primarie',
  useful: 'Utili',
  discretionary: 'Accessorie',
  savings: 'Risparmio',
}

const SPEND_BUCKETS: NecessityLevel[] = ['primary', 'useful', 'discretionary']

function useFormatAmount() {
  // Unlike BudgetsPage, which hardcodes EUR, read the user's actual base
  // currency — every figure on this page is already converted to it.
  const { user } = useAuth()
  const currency = user?.base_currency ?? 'EUR'
  return (amount: string | null) =>
    amount === null
      ? '—'
      : Number(amount).toLocaleString('it-IT', { style: 'currency', currency })
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  )
}

function BucketBar({
  bucket,
  format,
}: {
  bucket: AllocationBucketStatus
  format: (amount: string | null) => string
}) {
  // Over target is bad for the three spend buckets and good for savings, so
  // the colour follows the meaning rather than the raw comparison.
  const isGood = bucket.bucket === 'savings' ? bucket.is_over_target : !bucket.is_over_target
  const width = Math.min(Math.max(bucket.percentage_used, 0), 100)

  return (
    <div className="mb-4 last:mb-0">
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium text-slate-700">
          {BUCKET_LABELS[bucket.bucket]}{' '}
          <span className="text-xs text-slate-400">{Number(bucket.percentage)}%</span>
        </span>
        <span className={isGood ? 'text-slate-600' : 'font-medium text-red-600'}>
          {format(bucket.actual_amount)} / {format(bucket.target_amount)}
        </span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full ${isGood ? 'bg-slate-800' : 'bg-red-600'}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  )
}

function PlanForm({ onDone }: { onDone: () => void }) {
  const { data: plan } = usePlan()
  const { data: accounts } = useAccounts()
  const updatePlan = useUpdatePlan()
  const [values, setValues] = useState<Record<string, string> | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (!plan) return null

  const current = values ?? {
    pct_primary: String(Number(plan.pct_primary)),
    pct_useful: String(Number(plan.pct_useful)),
    pct_discretionary: String(Number(plan.pct_discretionary)),
    pct_savings: String(Number(plan.pct_savings)),
    lookback_months: String(plan.lookback_months),
    default_source_account_id: plan.default_source_account_id ?? '',
  }

  const total =
    Number(current.pct_primary) +
    Number(current.pct_useful) +
    Number(current.pct_discretionary) +
    Number(current.pct_savings)

  function set(field: string, value: string) {
    setValues({ ...current, [field]: value })
  }

  async function handleSave() {
    setError(null)
    try {
      await updatePlan.mutateAsync({
        pct_primary: current.pct_primary,
        pct_useful: current.pct_useful,
        pct_discretionary: current.pct_discretionary,
        pct_savings: current.pct_savings,
        lookback_months: Number(current.lookback_months),
        default_source_account_id: current.default_source_account_id || null,
      })
      onDone()
    } catch (e) {
      if (isAxiosError<ApiErrorResponse>(e) && e.response) {
        setError(e.response.data?.error?.message ?? 'Impossibile salvare il piano.')
      } else {
        setError('Impossibile salvare il piano.')
      }
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(['primary', 'useful', 'discretionary', 'savings'] as AllocationBucket[]).map((b) => (
          <div key={b}>
            <label htmlFor={`pct_${b}`} className="block text-xs font-medium text-slate-600">
              {BUCKET_LABELS[b]} %
            </label>
            <input
              id={`pct_${b}`}
              type="number"
              min={0}
              max={100}
              value={current[`pct_${b}`]}
              onChange={(e) => set(`pct_${b}`, e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
          </div>
        ))}
      </div>

      <p className={`text-xs ${total === 100 ? 'text-slate-400' : 'text-red-600'}`}>
        Totale: {total}% {total === 100 ? '' : '— deve fare esattamente 100'}
      </p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="lookback_months" className="block text-xs font-medium text-slate-600">
            Mesi di storico per le medie
          </label>
          <input
            id="lookback_months"
            type="number"
            min={1}
            max={60}
            value={current.lookback_months}
            onChange={(e) => set('lookback_months', e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
          />
        </div>
        <div>
          <label
            htmlFor="default_source_account_id"
            className="block text-xs font-medium text-slate-600"
          >
            Conto di accredito
          </label>
          <select
            id="default_source_account_id"
            value={current.default_source_account_id}
            onChange={(e) => set('default_source_account_id', e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
          >
            <option value="">Nessuno</option>
            {(accounts ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <button
        onClick={handleSave}
        disabled={updatePlan.isPending || total !== 100}
        className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {updatePlan.isPending ? 'Salvataggio...' : 'Salva piano'}
      </button>
    </div>
  )
}

function Simulator() {
  const { data: categories } = useCategories()
  const simulate = useSimulate()
  const format = useFormatAmount()
  const [bucketCuts, setBucketCuts] = useState<Record<string, number>>({
    primary: 0,
    useful: 0,
    discretionary: 0,
  })
  const [categoryId, setCategoryId] = useState('')
  const [categoryCut, setCategoryCut] = useState(0)

  const expenseCategories = (categories ?? []).filter((c) => c.type === 'expense')
  const result = simulate.data

  async function run() {
    const cuts: SimulationCut[] = SPEND_BUCKETS.filter((b) => bucketCuts[b] > 0).map((b) => ({
      necessity_level: b,
      cut_percentage: String(bucketCuts[b]),
    }))
    if (categoryId && categoryCut > 0) {
      cuts.push({ category_id: categoryId, cut_percentage: String(categoryCut) })
    }
    await simulate.mutateAsync({ cuts })
  }

  return (
    <div className="space-y-4">
      {SPEND_BUCKETS.map((b) => (
        <div key={b}>
          <div className="flex justify-between text-sm">
            <span className="text-slate-700">Taglia {BUCKET_LABELS[b]}</span>
            <span className="text-slate-500">{bucketCuts[b]}%</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={bucketCuts[b]}
            onChange={(e) => setBucketCuts({ ...bucketCuts, [b]: Number(e.target.value) })}
            aria-label={`Taglio ${BUCKET_LABELS[b]}`}
            className="w-full accent-slate-800"
          />
        </div>
      ))}

      <div className="rounded-md bg-slate-50 p-3">
        <p className="text-xs text-slate-500">
          Taglio su una singola categoria — ha la precedenza sul taglio del suo bucket.
        </p>
        <div className="mt-2 flex gap-2">
          <select
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            aria-label="Categoria da tagliare"
            className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Nessuna</option>
            {expenseCategories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input
            type="number"
            min={0}
            max={100}
            value={categoryCut}
            onChange={(e) => setCategoryCut(Number(e.target.value))}
            aria-label="Percentuale di taglio della categoria"
            className="w-20 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>
      </div>

      <button
        onClick={run}
        disabled={simulate.isPending}
        className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {simulate.isPending ? 'Calcolo...' : 'Simula'}
      </button>

      {result && (
        <div className="space-y-2 border-t border-slate-100 pt-4 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-600">Liberato</span>
            <span className="font-semibold text-green-600">{format(result.total_freed)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-600">Risparmio</span>
            <span className="text-slate-800">
              {format(result.baseline_savings_amount)} → {format(result.simulated_savings_amount)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-600">Tasso di risparmio</span>
            <span className="text-slate-800">
              {result.baseline_savings_rate}% → {result.simulated_savings_rate}%
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-600">Survival budget</span>
            <span className="text-slate-800">
              {format(result.baseline_survival_budget)} →{' '}
              {format(result.simulated_survival_budget)}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

export function PlanningPage() {
  const format = useFormatAmount()
  const { data: status, isLoading, isError } = useAllocationStatus()
  const { data: survival } = useSurvivalBudget()
  const [isEditingPlan, setIsEditingPlan] = useState(false)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Piano</h1>
        <button
          onClick={() => setIsEditingPlan((v) => !v)}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          {isEditingPlan ? 'Annulla' : 'Modifica piano'}
        </button>
      </div>

      {isEditingPlan && (
        <Card title="Modello di ripartizione">
          <PlanForm onDone={() => setIsEditingPlan(false)} />
        </Card>
      )}

      {isLoading && <p className="text-slate-500">Caricamento...</p>}
      {isError && <p className="text-red-600">Errore nel caricamento del piano.</p>}

      {status && (
        <>
          <Card title="Ripartizione del mese">
            <p className="mb-4 text-sm text-slate-500">
              Entrate del periodo: <strong>{format(status.income_total)}</strong>
            </p>
            {status.buckets.map((b) => (
              <BucketBar key={b.bucket} bucket={b} format={format} />
            ))}

            {Number(status.unclassified_amount) > 0 && (
              <p className="mt-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {format(status.unclassified_amount)} di spesa non è ancora classificato. Il piano è
                affidabile al {status.classification_coverage}% — assegna un livello di necessità
                alle categorie mancanti per completarlo.
              </p>
            )}
          </Card>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card title="Survival budget">
              {survival && survival.monthly_primary_expenses === null ? (
                <p className="text-sm text-slate-500">
                  Serve almeno un mese completo di storico per calcolarlo. Le medie ignorano il mese
                  in corso, che è ancora parziale.
                </p>
              ) : (
                survival && (
                  <dl className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <dt className="text-slate-600">Spese primarie mensili</dt>
                      <dd className="font-semibold text-slate-800">
                        {format(survival.monthly_primary_expenses)}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-slate-600">Spese totali mensili</dt>
                      <dd className="text-slate-800">{format(survival.monthly_total_expenses)}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-slate-600">Entrate mensili</dt>
                      <dd className="text-slate-800">{format(survival.monthly_income)}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-slate-600">Liquidità</dt>
                      <dd className="text-slate-800">{format(survival.total_cash_balance)}</dd>
                    </div>
                    <div className="flex justify-between border-t border-slate-100 pt-2">
                      <dt className="text-slate-600">Mesi di autonomia</dt>
                      <dd className="font-semibold text-slate-800">
                        {survival.months_of_runway ?? '—'}
                      </dd>
                    </div>
                    <p className="pt-2 text-xs text-slate-400">
                      Media su {survival.months_analysed} mes
                      {survival.months_analysed === 1 ? 'e' : 'i'} complet
                      {survival.months_analysed === 1 ? 'o' : 'i'}.
                    </p>
                  </dl>
                )
              )}
            </Card>

            <Card title="Simulatore di tagli">
              <Simulator />
            </Card>
          </div>

          <Card title="Cascata del risparmio">
            <WaterfallSection format={format} />
          </Card>
        </>
      )}
    </div>
  )
}
