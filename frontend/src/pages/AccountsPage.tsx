import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { isAxiosError } from 'axios'
import { TrashIcon } from '@/components/ui/Icon'
import { useAccounts, useCreateAccount, useDeleteAccount } from '@/hooks/useAccounts'
import type { ApiErrorResponse, AccountType } from '@/types'

const ACCOUNT_TYPES: { value: AccountType; label: string }[] = [
  { value: 'checking', label: 'Conto corrente' },
  { value: 'savings', label: 'Risparmio' },
  { value: 'credit_card', label: 'Carta di credito' },
  { value: 'investment', label: 'Investimento' },
  { value: 'crypto_wallet', label: 'Wallet crypto' },
]

// Same list as RegisterPage — kept separate for now since each page's
// currency list could diverge later (e.g. accounts might support more
// currencies than a user's base_currency choices).
const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'] as const

const accountSchema = z.object({
  name: z.string().min(1, 'Il nome è obbligatorio').max(100),
  type: z.enum(['checking', 'savings', 'credit_card', 'investment', 'crypto_wallet']),
  currency: z.enum(CURRENCIES),
  starting_balance: z
    .string()
    .optional()
    .refine((v) => !v || !Number.isNaN(Number(v)), 'Inserisci un numero valido'),
})

type AccountFormValues = z.infer<typeof accountSchema>

export function AccountsPage() {
  const { data: accounts, isLoading, isError } = useAccounts()
  const createAccount = useCreateAccount()
  const deleteAccount = useDeleteAccount()
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AccountFormValues>({
    resolver: zodResolver(accountSchema),
    defaultValues: { type: 'checking', currency: 'EUR' },
  })

  async function onSubmit(values: AccountFormValues) {
    setFormError(null)
    try {
      await createAccount.mutateAsync({
        ...values,
        starting_balance: values.starting_balance || undefined,
      })
      reset()
      setIsFormOpen(false)
    } catch (error) {
      if (isAxiosError<ApiErrorResponse>(error) && error.response) {
        setFormError(error.response.data?.error?.message ?? 'Impossibile creare il conto. Riprova.')
      } else {
        setFormError('Impossibile creare il conto. Riprova.')
      }
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(`Eliminare il conto "${name}"?`)) return
    await deleteAccount.mutateAsync(id)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Conti</h1>
        <button
          onClick={() => setIsFormOpen((open) => !open)}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          {isFormOpen ? 'Annulla' : 'Nuovo conto'}
        </button>
      </div>

      {isFormOpen && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="grid grid-cols-1 gap-4 rounded-lg bg-white p-6 shadow-sm sm:grid-cols-3"
          noValidate
        >
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-slate-700">
              Nome
            </label>
            <input
              id="name"
              {...register('name')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.name && <p className="mt-1 text-sm text-red-600">{errors.name.message}</p>}
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
              {ACCOUNT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="currency" className="block text-sm font-medium text-slate-700">
              Valuta
            </label>
            <select
              id="currency"
              {...register('currency')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              {CURRENCIES.map((currency) => (
                <option key={currency} value={currency}>
                  {currency}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="starting_balance" className="block text-sm font-medium text-slate-700">
              Saldo iniziale (opzionale)
            </label>
            <input
              id="starting_balance"
              placeholder="0.00"
              {...register('starting_balance')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.starting_balance && (
              <p className="mt-1 text-sm text-red-600">{errors.starting_balance.message}</p>
            )}
          </div>

          <div className="sm:col-span-3">
            {formError && <p className="mb-2 text-sm text-red-600">{formError}</p>}
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {isSubmitting ? 'Creazione...' : 'Crea conto'}
            </button>
          </div>
        </form>
      )}

      <div className="rounded-lg bg-white shadow-sm">
        {isLoading && <p className="p-6 text-slate-500">Caricamento...</p>}
        {isError && <p className="p-6 text-red-600">Errore nel caricamento dei conti.</p>}

        {accounts && accounts.length === 0 && (
          <p className="p-6 text-sm text-slate-500">Nessun conto ancora. Creane uno per iniziare.</p>
        )}

        {accounts && accounts.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {accounts.map((account) => (
              <li key={account.id} className="flex items-center justify-between px-6 py-4">
                <div>
                  <p className="text-sm font-medium text-slate-800">{account.name}</p>
                  <p className="text-xs text-slate-400">
                    {ACCOUNT_TYPES.find((t) => t.value === account.type)?.label} · {account.currency}
                  </p>
                </div>
                <button
                  onClick={() => handleDelete(account.id, account.name)}
                  aria-label="Elimina"
                  title="Elimina"
                  className="rounded p-1.5 text-red-600 hover:bg-red-50"
                >
                  <TrashIcon />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
