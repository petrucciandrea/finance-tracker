import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { isAxiosError } from 'axios'
import { useAuth } from '@/hooks/useAuth'
import type { ApiErrorResponse } from '@/types'

// Kept in sync with the currencies seeded in the backend (see the
// 0002_seed_currencies migration) — same list used on the register form.
const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'] as const

const profileSchema = z.object({
  email: z.string().email('Inserisci un indirizzo email valido'),
  base_currency: z.enum(CURRENCIES),
  first_name: z.string().max(100, 'Massimo 100 caratteri').optional(),
  last_name: z.string().max(100, 'Massimo 100 caratteri').optional(),
  date_of_birth: z.string().optional(),
})

type ProfileFormValues = z.infer<typeof profileSchema>

const passwordSchema = z
  .object({
    current_password: z.string().min(1, 'Inserisci la password attuale'),
    new_password: z.string().min(8, 'La nuova password deve avere almeno 8 caratteri'),
    confirm_password: z.string().min(1, 'Conferma la nuova password'),
  })
  .refine((values) => values.new_password === values.confirm_password, {
    message: 'Le password non coincidono',
    path: ['confirm_password'],
  })

type PasswordFormValues = z.infer<typeof passwordSchema>

export function ProfilePage() {
  const { user, updateProfile, changePassword } = useAuth()
  const [profileMessage, setProfileMessage] = useState<string | null>(null)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)

  const {
    register: registerProfile,
    handleSubmit: handleProfileSubmit,
    formState: { errors: profileErrors, isSubmitting: isProfileSubmitting },
  } = useForm<ProfileFormValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      email: user?.email ?? '',
      base_currency: (user?.base_currency as (typeof CURRENCIES)[number]) ?? 'EUR',
      first_name: user?.first_name ?? '',
      last_name: user?.last_name ?? '',
      date_of_birth: user?.date_of_birth ?? '',
    },
  })

  const {
    register: registerPassword,
    handleSubmit: handlePasswordSubmit,
    reset: resetPasswordForm,
    formState: { errors: passwordErrors, isSubmitting: isPasswordSubmitting },
  } = useForm<PasswordFormValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: '', new_password: '', confirm_password: '' },
  })

  async function onProfileSubmit(values: ProfileFormValues) {
    setProfileMessage(null)
    setProfileError(null)
    try {
      await updateProfile({
        email: values.email,
        base_currency: values.base_currency,
        // An empty field means "clear it" — send null rather than "" so it
        // round-trips through the backend as an actual absence of data.
        first_name: values.first_name || null,
        last_name: values.last_name || null,
        date_of_birth: values.date_of_birth || null,
      })
      setProfileMessage('Dati aggiornati con successo.')
    } catch (error) {
      if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 409) {
        setProfileError('Esiste già un account con questa email.')
      } else {
        setProfileError('Si è verificato un errore. Riprova.')
      }
    }
  }

  async function onPasswordSubmit(values: PasswordFormValues) {
    setPasswordMessage(null)
    setPasswordError(null)
    try {
      await changePassword({
        current_password: values.current_password,
        new_password: values.new_password,
      })
      setPasswordMessage('Password aggiornata con successo.')
      resetPasswordForm()
    } catch (error) {
      if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 401) {
        setPasswordError('La password attuale non è corretta.')
      } else {
        setPasswordError('Si è verificato un errore. Riprova.')
      }
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold text-slate-800">Profilo</h1>

      <div className="rounded-lg bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold text-slate-800">Dati account</h2>
        <form onSubmit={handleProfileSubmit(onProfileSubmit)} className="space-y-4" noValidate>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-slate-700">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              {...registerProfile('email')}
              className="mt-1 w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {profileErrors.email && (
              <p className="mt-1 text-sm text-red-600">{profileErrors.email.message}</p>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="first_name" className="block text-sm font-medium text-slate-700">
                Nome
              </label>
              <input
                id="first_name"
                autoComplete="given-name"
                {...registerProfile('first_name')}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
              />
              {profileErrors.first_name && (
                <p className="mt-1 text-sm text-red-600">{profileErrors.first_name.message}</p>
              )}
            </div>

            <div>
              <label htmlFor="last_name" className="block text-sm font-medium text-slate-700">
                Cognome
              </label>
              <input
                id="last_name"
                autoComplete="family-name"
                {...registerProfile('last_name')}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
              />
              {profileErrors.last_name && (
                <p className="mt-1 text-sm text-red-600">{profileErrors.last_name.message}</p>
              )}
            </div>
          </div>

          <div>
            <label htmlFor="date_of_birth" className="block text-sm font-medium text-slate-700">
              Data di nascita
            </label>
            <input
              id="date_of_birth"
              type="date"
              autoComplete="bday"
              {...registerProfile('date_of_birth')}
              className="mt-1 w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {profileErrors.date_of_birth && (
              <p className="mt-1 text-sm text-red-600">{profileErrors.date_of_birth.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="base_currency" className="block text-sm font-medium text-slate-700">
              Valuta di riferimento
            </label>
            <select
              id="base_currency"
              {...registerProfile('base_currency')}
              className="mt-1 w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              {CURRENCIES.map((currency) => (
                <option key={currency} value={currency}>
                  {currency}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-slate-400">
              Cambiarla non ricalcola le transazioni passate, solo quelle future.
            </p>
          </div>

          {profileMessage && <p className="text-sm text-green-700">{profileMessage}</p>}
          {profileError && <p className="text-sm text-red-600">{profileError}</p>}

          <button
            type="submit"
            disabled={isProfileSubmitting}
            className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {isProfileSubmitting ? 'Salvataggio...' : 'Salva modifiche'}
          </button>
        </form>
      </div>

      <div className="rounded-lg bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold text-slate-800">Cambia password</h2>
        <form onSubmit={handlePasswordSubmit(onPasswordSubmit)} className="space-y-4" noValidate>
          <div>
            <label htmlFor="current_password" className="block text-sm font-medium text-slate-700">
              Password attuale
            </label>
            <input
              id="current_password"
              type="password"
              autoComplete="current-password"
              {...registerPassword('current_password')}
              className="mt-1 w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {passwordErrors.current_password && (
              <p className="mt-1 text-sm text-red-600">{passwordErrors.current_password.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="new_password" className="block text-sm font-medium text-slate-700">
              Nuova password
            </label>
            <input
              id="new_password"
              type="password"
              autoComplete="new-password"
              {...registerPassword('new_password')}
              className="mt-1 w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {passwordErrors.new_password && (
              <p className="mt-1 text-sm text-red-600">{passwordErrors.new_password.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="confirm_password" className="block text-sm font-medium text-slate-700">
              Conferma nuova password
            </label>
            <input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              {...registerPassword('confirm_password')}
              className="mt-1 w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {passwordErrors.confirm_password && (
              <p className="mt-1 text-sm text-red-600">{passwordErrors.confirm_password.message}</p>
            )}
          </div>

          {passwordMessage && <p className="text-sm text-green-700">{passwordMessage}</p>}
          {passwordError && <p className="text-sm text-red-600">{passwordError}</p>}

          <button
            type="submit"
            disabled={isPasswordSubmitting}
            className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {isPasswordSubmitting ? 'Aggiornamento...' : 'Aggiorna password'}
          </button>
        </form>
      </div>
    </div>
  )
}
