import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { isAxiosError } from 'axios'
import type { ApiErrorResponse } from '@/types'

// Kept in sync with the currencies seeded in the backend (see the
// 0002_seed_currencies migration) — a dropdown avoids free-text typos
// that would 422 against the /accounts currency FK check anyway.
const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'] as const

const registerSchema = z.object({
  email: z.string().email('Inserisci un indirizzo email valido'),
  password: z.string().min(8, 'La password deve avere almeno 8 caratteri'),
  base_currency: z.enum(CURRENCIES),
})

type RegisterFormValues = z.infer<typeof registerSchema>

export function RegisterPage() {
  const { register: registerUser } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { base_currency: 'EUR' },
  })

  async function onSubmit(values: RegisterFormValues) {
    setServerError(null)
    try {
      await registerUser(values)
      navigate('/', { replace: true })
    } catch (error) {
      if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 409) {
        setServerError('Esiste già un account con questa email')
      } else {
        setServerError('Si è verificato un errore. Riprova.')
      }
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-lg bg-white p-8 shadow-sm">
        <h1 className="mb-6 text-2xl font-semibold text-slate-800">Crea un account</h1>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-slate-700">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              {...register('email')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.email && <p className="mt-1 text-sm text-red-600">{errors.email.message}</p>}
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-700">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              {...register('password')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.password && <p className="mt-1 text-sm text-red-600">{errors.password.message}</p>}
          </div>

          <div>
            <label htmlFor="base_currency" className="block text-sm font-medium text-slate-700">
              Valuta di riferimento
            </label>
            <select
              id="base_currency"
              {...register('base_currency')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              {CURRENCIES.map((currency) => (
                <option key={currency} value={currency}>
                  {currency}
                </option>
              ))}
            </select>
          </div>

          {serverError && <p className="text-sm text-red-600">{serverError}</p>}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {isSubmitting ? 'Creazione account...' : 'Registrati'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-slate-500">
          Hai già un account?{' '}
          <Link to="/login" className="font-medium text-slate-800 hover:underline">
            Accedi
          </Link>
        </p>
      </div>
    </div>
  )
}
