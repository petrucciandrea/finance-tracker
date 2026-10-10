import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link, useNavigate } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { ErrorBlock, Notice } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { useAuth } from '@/hooks/useAuth'
import { usePublicConfig } from '@/hooks/usePublicConfig'
import { CURRENCIES, CURRENCY_NAMES } from '@/lib/currencies'
import type { ApiErrorResponse, User } from '@/types'

const registerSchema = z.object({
  email: z.string().email('Inserisci un indirizzo email valido'),
  password: z.string().min(8, 'La password deve avere almeno 8 caratteri'),
  base_currency: z.enum(CURRENCIES),
  accept_terms: z.boolean().refine((accepted) => accepted, 'Per registrarti devi accettare privacy e termini'),
})

type RegisterFormValues = z.infer<typeof registerSchema>

export function RegisterPage() {
  const { register: registerUser } = useAuth()
  const { registrationClosed } = usePublicConfig()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const [created, setCreated] = useState<User | null>(null)

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
      const user = await registerUser(values)
      if (user.approval_status === 'approved' && user.email_verified_at) {
        navigate('/', { replace: true })
      } else {
        setCreated(user)
      }
    } catch (error) {
      if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 409) {
        setServerError('Esiste già un account con questa email')
      } else if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 429) {
        setServerError('Troppi tentativi. Riprova tra qualche minuto.')
      } else {
        setServerError('Si è verificato un errore. Riprova.')
      }
    }
  }

  if (registrationClosed) {
    return (
      <AuthLayout title="Registrazioni chiuse" subtitle="Al momento non si possono creare nuovi account.">
        <div className="mt-6 flex flex-col gap-4">
          <Notice tone="info">Registrazioni chiuse</Notice>
          <Link to="/login" className="link">
            Vai al login
          </Link>
        </div>
      </AuthLayout>
    )
  }

  if (created) {
    const needsVerification = !created.email_verified_at
    const needsApproval = created.approval_status === 'pending'
    return (
      <AuthLayout title="Quasi fatto" subtitle="Ancora un passaggio prima di poter accedere.">
        <div className="mt-6 flex flex-col gap-4">
          {needsVerification && !needsApproval && (
            <p className="text-[15px] text-ink-2">
              Abbiamo mandato un link di conferma a <strong className="text-ink">{created.email}</strong>. Aprilo per
              verificare l&apos;indirizzo (controlla anche lo spam).
            </p>
          )}
          {needsApproval && (
            <>
              <Notice tone="info">In attesa di approvazione</Notice>
              <p className="text-[15px] text-ink-2">
                Le registrazioni sono su approvazione. Appena la tua richiesta verrà approvata riceverai
                un&apos;email: conferma il tuo indirizzo dal link che contiene e potrai accedere con la password che
                hai scelto.
              </p>
            </>
          )}
          <Link to="/login" className="link">
            Vai al login
          </Link>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Crea il tuo account" subtitle="Ti servono solo email, password e la valuta in cui ragionare.">
      <form onSubmit={handleSubmit(onSubmit)} className="mt-6 flex flex-col gap-[18px]" noValidate>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <input
            id="email"
            type="email"
            autoComplete="email"
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? 'email-msg' : undefined}
            className="field min-h-12"
            {...register('email')}
          />
        </Field>

        <Field label="Password" htmlFor="password" error={errors.password?.message} hint="Almeno 8 caratteri.">
          <PasswordInput
            id="password"
            autoComplete="new-password"
            aria-invalid={!!errors.password}
            aria-describedby="password-msg"
            className="min-h-12"
            {...register('password')}
          />
        </Field>

        <Field
          label="Valuta base"
          htmlFor="base_currency"
          hint="Totali e grafici saranno convertiti in questa valuta. Puoi cambiarla dal profilo."
        >
          <select id="base_currency" aria-describedby="base_currency-msg" className="field min-h-12" {...register('base_currency')}>
            {CURRENCIES.map((currency) => (
              <option key={currency} value={currency}>
                {currency} · {CURRENCY_NAMES[currency]}
              </option>
            ))}
          </select>
        </Field>

        <div>
          <label className="flex min-h-11 cursor-pointer items-start gap-3 text-[14px] text-ink-2">
            <input
              id="accept_terms"
              type="checkbox"
              aria-invalid={!!errors.accept_terms}
              aria-describedby={errors.accept_terms ? 'accept_terms-msg' : undefined}
              className="mt-0.5 h-5 w-5 flex-none cursor-pointer"
              {...register('accept_terms')}
            />
            <span>
              Ho letto e accetto l&apos;
              <Link to="/privacy" target="_blank" className="link">
                informativa sulla privacy
              </Link>{' '}
              e i{' '}
              <Link to="/termini" target="_blank" className="link">
                termini di servizio
              </Link>
              .
            </span>
          </label>
          {errors.accept_terms && (
            <p id="accept_terms-msg" role="alert" className="mt-1.5 text-[13px] font-bold text-neg">
              ✕ {errors.accept_terms.message}
            </p>
          )}
        </div>

        {serverError && <ErrorBlock>{serverError}</ErrorBlock>}

        <Button type="submit" variant="primary" disabled={isSubmitting} className="mt-1 min-h-[50px] text-[16px] font-extrabold">
          {isSubmitting ? 'Creazione account…' : 'Crea account'}
        </Button>
      </form>

      <p className="mt-5 text-center text-[14px] text-ink-2">
        Hai già un account?{' '}
        <Link to="/login" className="link">
          Accedi
        </Link>
      </p>
    </AuthLayout>
  )
}
