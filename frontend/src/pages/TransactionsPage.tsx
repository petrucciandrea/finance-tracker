import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { TransactionImport } from '@/components/transactions/TransactionImport'
import { TrashIcon } from '@/components/ui/Icon'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import {
  useCreateTransaction,
  useDeleteTransaction,
  useTransactionsList,
} from '@/hooks/useTransactions'
import type { Category, NecessityLevel, Transaction, TransactionType } from '@/types'

type PanelMode = 'none' | 'form' | 'import'

const TRANSACTION_TYPES: { value: TransactionType; label: string }[] = [
  { value: 'expense', label: 'Spesa' },
  { value: 'income', label: 'Entrata' },
  { value: 'transfer', label: 'Trasferimento' },
]

type CategoryOption =
  | { kind: 'leaf'; category: Category }
  | { kind: 'group'; parent: Category; children: Category[] }

/**
 * A category with active subcategories can't be assigned to a transaction
 * directly (the backend rejects it — a subcategory must be picked instead),
 * so parents with children render as a non-selectable optgroup label and
 * only their children/childless roots are actual options. Also scoped to
 * the transaction's own type — a category's type must match the
 * transaction's (expense/income/transfer), same rule the backend enforces.
 */
function buildCategoryOptions(categories: Category[] | undefined, type: TransactionType): CategoryOption[] {
  if (!categories) return []
  const relevant = categories.filter((c) => c.type === type)
  const roots = relevant.filter((c) => c.parent_id === null)
  return roots.map((root) => {
    const children = relevant.filter((c) => c.parent_id === root.id)
    return children.length > 0
      ? { kind: 'group' as const, parent: root, children }
      : { kind: 'leaf' as const, category: root }
  })
}

const NECESSITY_LABELS: Record<NecessityLevel, string> = {
  primary: 'Primario',
  useful: 'Utile',
  discretionary: 'Accessorio',
}

// Mirrors the backend's COALESCE(override, category, parent) so the list can
// show the level that actually applies, and mark whether it came from an
// override or was inherited.
function effectiveNecessity(
  transaction: Transaction,
  category: Category | undefined,
  categories: Category[] | undefined,
): { level: NecessityLevel; isOverride: boolean } | null {
  if (transaction.type !== 'expense') return null
  if (transaction.necessity_level_override) {
    return { level: transaction.necessity_level_override, isOverride: true }
  }
  if (category?.necessity_level) {
    return { level: category.necessity_level, isOverride: false }
  }
  const parent = category?.parent_id
    ? categories?.find((c) => c.id === category.parent_id)
    : undefined
  if (parent?.necessity_level) {
    return { level: parent.necessity_level, isOverride: false }
  }
  return null
}

const transactionSchema = z.object({
  account_id: z.string().min(1, 'Seleziona un conto'),
  category_id: z.string().optional(),
  amount: z
    .string()
    .min(1, 'Importo obbligatorio')
    .refine((v) => !Number.isNaN(Number(v)), 'Inserisci un numero valido'),
  currency: z.string().length(3, 'Codice valuta di 3 lettere'),
  date: z.string().min(1, 'Data obbligatoria'),
  description: z.string().optional(),
  type: z.enum(['expense', 'income', 'transfer']),
  // Expense only — the backend 422s an override on income/transfer, since a
  // necessity level has no meaning there.
  necessity_level_override: z.enum(['primary', 'useful', 'discretionary']).or(z.literal('')).optional(),
})

type TransactionFormValues = z.infer<typeof transactionSchema>

function formatAmount(amount: string, currency: string): string {
  return Number(amount).toLocaleString('it-IT', { style: 'currency', currency })
}

export function TransactionsPage() {
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const [categoryFilter, setCategoryFilter] = useState<string>('')
  const [panel, setPanel] = useState<PanelMode>('none')

  function togglePanel(mode: PanelMode) {
    setPanel((current) => (current === mode ? 'none' : mode))
  }

  const { data: transactionsData, isLoading, isError } = useTransactionsList({
    category_id: categoryFilter || undefined,
    page: 1,
    page_size: 50,
  })

  const createTransaction = useCreateTransaction()
  const deleteTransaction = useDeleteTransaction()

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<TransactionFormValues>({
    resolver: zodResolver(transactionSchema),
    defaultValues: {
      type: 'expense',
      currency: 'EUR',
      date: new Date().toISOString().slice(0, 10),
    },
  })

  const selectedType = watch('type')
  const categoryOptions = buildCategoryOptions(categories, selectedType)

  async function onSubmit(values: TransactionFormValues) {
    // Sign convention matches the backend's design: expenses are negative,
    // income positive. The form takes a plain positive number and applies
    // the sign here so the user doesn't have to type a minus themselves.
    const signedAmount =
      values.type === 'expense' ? `-${Math.abs(Number(values.amount))}` : String(Math.abs(Number(values.amount)))

    await createTransaction.mutateAsync({
      account_id: values.account_id,
      category_id: values.category_id || null,
      amount: signedAmount,
      currency: values.currency,
      date: values.date,
      description: values.description || null,
      type: values.type,
      necessity_level_override:
        values.type === 'expense' && values.necessity_level_override
          ? values.necessity_level_override
          : null,
    })
    reset({
      type: 'expense',
      currency: 'EUR',
      date: new Date().toISOString().slice(0, 10),
      account_id: '',
      category_id: '',
      amount: '',
      description: '',
      necessity_level_override: '',
    })
    setPanel('none')
  }

  async function handleDelete(id: string) {
    if (!window.confirm('Eliminare questa transazione?')) return
    await deleteTransaction.mutateAsync(id)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Transazioni</h1>
        <div className="flex gap-2">
          <button
            onClick={() => togglePanel('import')}
            className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            {panel === 'import' ? 'Annulla' : 'Importa CSV'}
          </button>
          <button
            onClick={() => togglePanel('form')}
            className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            {panel === 'form' ? 'Annulla' : 'Nuova transazione'}
          </button>
        </div>
      </div>

      {panel === 'import' && <TransactionImport onDone={() => setPanel('none')} />}

      {panel === 'form' && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="grid grid-cols-1 gap-4 rounded-lg bg-white p-6 shadow-sm sm:grid-cols-3"
          noValidate
        >
          <div>
            <label htmlFor="account_id" className="block text-sm font-medium text-slate-700">
              Conto
            </label>
            <select
              id="account_id"
              {...register('account_id')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="">Seleziona un conto</option>
              {accounts?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.currency})
                </option>
              ))}
            </select>
            {errors.account_id && <p className="mt-1 text-sm text-red-600">{errors.account_id.message}</p>}
          </div>

          <div>
            <label htmlFor="category_id" className="block text-sm font-medium text-slate-700">
              Categoria (opzionale)
            </label>
            <select
              id="category_id"
              {...register('category_id')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="">Nessuna categoria</option>
              {categoryOptions.map((opt) =>
                opt.kind === 'leaf' ? (
                  <option key={opt.category.id} value={opt.category.id}>
                    {opt.category.name}
                  </option>
                ) : (
                  <optgroup key={opt.parent.id} label={opt.parent.name}>
                    {opt.children.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </optgroup>
                ),
              )}
            </select>
          </div>

          <div>
            <label htmlFor="type" className="block text-sm font-medium text-slate-700">
              Tipo
            </label>
            <select
              id="type"
              {...register('type')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              {TRANSACTION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="amount" className="block text-sm font-medium text-slate-700">
              Importo
            </label>
            <input
              id="amount"
              type="number"
              step="0.01"
              placeholder="0.00"
              {...register('amount')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.amount && <p className="mt-1 text-sm text-red-600">{errors.amount.message}</p>}
          </div>

          <div>
            <label htmlFor="currency" className="block text-sm font-medium text-slate-700">
              Valuta
            </label>
            <input
              id="currency"
              maxLength={3}
              {...register('currency')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm uppercase focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.currency && <p className="mt-1 text-sm text-red-600">{errors.currency.message}</p>}
          </div>

          <div>
            <label htmlFor="date" className="block text-sm font-medium text-slate-700">
              Data
            </label>
            <input
              id="date"
              type="date"
              {...register('date')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.date && <p className="mt-1 text-sm text-red-600">{errors.date.message}</p>}
          </div>

          {selectedType === 'expense' && (
            <div className="sm:col-span-3">
              <label
                htmlFor="necessity_level_override"
                className="block text-sm font-medium text-slate-700"
              >
                Livello di necessità (opzionale)
              </label>
              <select
                id="necessity_level_override"
                {...register('necessity_level_override')}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
              >
                <option value="">Eredita dalla categoria</option>
                {(Object.keys(NECESSITY_LABELS) as NecessityLevel[]).map((level) => (
                  <option key={level} value={level}>
                    {NECESSITY_LABELS[level]}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-400">
                Usalo solo per le eccezioni — ad esempio una cena di lavoro sotto "Ristoranti".
              </p>
            </div>
          )}

          <div className="sm:col-span-3">
            <label htmlFor="description" className="block text-sm font-medium text-slate-700">
              Descrizione (opzionale)
            </label>
            <input
              id="description"
              {...register('description')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
          </div>

          <div className="sm:col-span-3">
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {isSubmitting ? 'Creazione...' : 'Crea transazione'}
            </button>
          </div>
        </form>
      )}

      <div className="flex items-center gap-3">
        <label htmlFor="category-filter" className="text-sm font-medium text-slate-700">
          Filtra per categoria:
        </label>
        <select
          id="category-filter"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          <option value="">Tutte</option>
          {categories?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <div className="rounded-lg bg-white shadow-sm">
        {isLoading && <p className="p-6 text-slate-500">Caricamento...</p>}
        {isError && <p className="p-6 text-red-600">Errore nel caricamento delle transazioni.</p>}

        {transactionsData && transactionsData.data.length === 0 && (
          <p className="p-6 text-sm text-slate-500">Nessuna transazione trovata.</p>
        )}

        {transactionsData && transactionsData.data.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {transactionsData.data.map((t) => {
              const category = categories?.find((c) => c.id === t.category_id)
              const account = accounts?.find((a) => a.id === t.account_id)
              const necessity = effectiveNecessity(t, category, categories)
              return (
                <li key={t.id} className="flex items-center justify-between px-6 py-4">
                  <div>
                    <p className="text-sm font-medium text-slate-800">
                      {t.description || category?.name || 'Senza descrizione'}
                    </p>
                    <p className="text-xs text-slate-400">
                      {t.date} · {account?.name ?? 'Conto eliminato'}
                      {category && ` · ${category.name}`}
                    </p>
                    {necessity && (
                      <span
                        className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[11px] ${
                          necessity.isOverride
                            ? 'bg-slate-800 text-white'
                            : 'bg-slate-100 text-slate-500'
                        }`}
                        title={
                          necessity.isOverride
                            ? 'Livello impostato su questa transazione'
                            : 'Livello ereditato dalla categoria'
                        }
                      >
                        {NECESSITY_LABELS[necessity.level]}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4">
                    <p
                      className={`text-sm font-semibold ${
                        Number(t.amount) < 0 ? 'text-red-600' : 'text-green-600'
                      }`}
                    >
                      {formatAmount(t.amount, t.currency)}
                    </p>
                    <button
                      onClick={() => handleDelete(t.id)}
                      aria-label="Elimina"
                      title="Elimina"
                      className="rounded p-1.5 text-red-600 hover:bg-red-50"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}

        {transactionsData && transactionsData.meta.total_pages > 1 && (
          <p className="border-t border-slate-100 px-6 py-3 text-xs text-slate-400">
            Pagina {transactionsData.meta.page} di {transactionsData.meta.total_pages} ·{' '}
            {transactionsData.meta.total_items} transazioni totali
          </p>
        )}
      </div>
    </div>
  )
}
