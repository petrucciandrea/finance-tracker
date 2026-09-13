import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { isAxiosError } from 'axios'
import { TrashIcon } from '@/components/ui/Icon'
import { useCategories } from '@/hooks/useCategories'
import {
  useBudgets,
  useBudgetsStatus,
  useCreateBudget,
  useDeleteBudget,
} from '@/hooks/useBudgets'
import type { ApiErrorResponse, BudgetPeriod } from '@/types'

const PERIOD_LABELS: Record<BudgetPeriod, string> = {
  monthly: 'Mensile',
  yearly: 'Annuale',
}

const budgetSchema = z.object({
  category_id: z.string().min(1, 'Seleziona una categoria'),
  period: z.enum(['monthly', 'yearly']),
  amount_limit: z
    .string()
    .min(1, 'Importo obbligatorio')
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, 'Inserisci un numero positivo'),
  start_date: z.string().min(1, 'Data obbligatoria'),
})

type BudgetFormValues = z.infer<typeof budgetSchema>

function formatAmount(amount: string): string {
  return Number(amount).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' })
}

export function BudgetsPage() {
  const { data: categories } = useCategories()
  const { data: budgets, isLoading, isError } = useBudgets()
  const { data: statusList } = useBudgetsStatus()
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const createBudget = useCreateBudget()
  const deleteBudget = useDeleteBudget()

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<BudgetFormValues>({
    resolver: zodResolver(budgetSchema),
    defaultValues: { period: 'monthly', start_date: new Date().toISOString().slice(0, 10) },
  })

  // Budgets only apply to expense categories — the backend rejects income
  // categories with a 422, filtering here just avoids the round-trip.
  const expenseCategories = (categories ?? []).filter((c) => c.type === 'expense')

  async function onSubmit(values: BudgetFormValues) {
    setFormError(null)
    try {
      await createBudget.mutateAsync(values)
      reset()
      setIsFormOpen(false)
    } catch (error) {
      if (isAxiosError<ApiErrorResponse>(error) && error.response) {
        setFormError(error.response.data?.error?.message ?? 'Impossibile creare il budget. Riprova.')
      } else {
        setFormError('Impossibile creare il budget. Riprova.')
      }
    }
  }

  async function handleDelete(id: string, categoryName: string) {
    if (!window.confirm(`Eliminare il budget su "${categoryName}"?`)) return
    await deleteBudget.mutateAsync(id)
  }

  const statusByCategory = new Map((statusList ?? []).map((s) => [s.category_id, s]))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Budget</h1>
        <button
          onClick={() => setIsFormOpen((open) => !open)}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          {isFormOpen ? 'Annulla' : 'Nuovo budget'}
        </button>
      </div>

      {isFormOpen && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="grid grid-cols-1 gap-4 rounded-lg bg-white p-6 shadow-sm sm:grid-cols-4"
          noValidate
        >
          <div>
            <label htmlFor="category_id" className="block text-sm font-medium text-slate-700">
              Categoria
            </label>
            <select
              id="category_id"
              {...register('category_id')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="">Seleziona...</option>
              {expenseCategories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {errors.category_id && (
              <p className="mt-1 text-sm text-red-600">{errors.category_id.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="period" className="block text-sm font-medium text-slate-700">
              Periodo
            </label>
            <select
              id="period"
              {...register('period')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="monthly">Mensile</option>
              <option value="yearly">Annuale</option>
            </select>
          </div>

          <div>
            <label htmlFor="amount_limit" className="block text-sm font-medium text-slate-700">
              Limite
            </label>
            <input
              id="amount_limit"
              {...register('amount_limit')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.amount_limit && (
              <p className="mt-1 text-sm text-red-600">{errors.amount_limit.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="start_date" className="block text-sm font-medium text-slate-700">
              Data inizio
            </label>
            <input
              id="start_date"
              type="date"
              {...register('start_date')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.start_date && (
              <p className="mt-1 text-sm text-red-600">{errors.start_date.message}</p>
            )}
          </div>

          <div className="sm:col-span-4">
            {formError && <p className="mb-2 text-sm text-red-600">{formError}</p>}
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {isSubmitting ? 'Creazione...' : 'Crea budget'}
            </button>
          </div>
        </form>
      )}

      <div className="rounded-lg bg-white shadow-sm">
        {isLoading && <p className="p-6 text-slate-500">Caricamento...</p>}
        {isError && <p className="p-6 text-red-600">Errore nel caricamento dei budget.</p>}

        {budgets && budgets.length === 0 && (
          <p className="p-6 text-sm text-slate-500">Nessun budget ancora. Creane uno per iniziare.</p>
        )}

        {budgets && budgets.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {budgets.map((budget) => {
              const status = statusByCategory.get(budget.category_id)
              const categoryName = status?.category_name ?? '—'
              return (
                <li key={budget.id} className="px-6 py-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-slate-800">{categoryName}</p>
                      <p className="text-xs text-slate-400">
                        {PERIOD_LABELS[budget.period]} · limite {formatAmount(budget.amount_limit)}
                      </p>
                    </div>
                    <button
                      onClick={() => handleDelete(budget.id, categoryName)}
                      aria-label="Elimina"
                      title="Elimina"
                      className="rounded p-1.5 text-red-600 hover:bg-red-50"
                    >
                      <TrashIcon />
                    </button>
                  </div>

                  {status && (
                    <div className="mt-3">
                      <div className="flex items-center justify-between text-xs text-slate-500">
                        <span
                          className={status.is_over_budget ? 'font-medium text-red-600' : 'text-slate-500'}
                        >
                          {formatAmount(status.amount_spent)} di {formatAmount(status.amount_limit)}
                        </span>
                        <span className={status.is_over_budget ? 'font-medium text-red-600' : ''}>
                          {status.percentage_used}%
                        </span>
                      </div>
                      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={`h-full ${status.is_over_budget ? 'bg-red-600' : 'bg-slate-800'}`}
                          style={{ width: `${Math.min(status.percentage_used, 100)}%` }}
                        />
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
