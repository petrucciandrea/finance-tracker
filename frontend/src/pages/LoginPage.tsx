import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link, useNavigate } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { PasswordInput } from '@/components/ui/PasswordInput'
import * as authApi from '@/api/auth'
import { useAuth } from '@/hooks/useAuth'
import type { ApiErrorResponse } from '@/types'

const loginSchema = z.object({
  email: z.string().email('Inserisci un indirizzo email valido'),
  password: z.string().min(1, 'La password è obbligatoria'),
})

type LoginFormValues = z.infer<typeof loginSchema>

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const [needsVerification, setNeedsVerification] = useState(false)
  const [resent, setResent] = useState(false)

  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) })

  async function onSubmit(values: LoginFormValues) {
    setServerError(null)
    setNeedsVerification(false)
    setResent(false)
    try {
      await login(values)
      navigate('/', { replace: true })
    } catch (error) {
      // Same message the backend intentionally uses for both "unknown
      // email" and "wrong password" — don't try to be more specific here,
      // that would defeat the point of the backend's choice.
      if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 401) {
        setServerError('Email o password non corretti')
      } else if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 429) {
        setServerError('Troppi tentativi. Riprova tra qualche minuto.')
      } else if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 403) {
        // Only answered after the password matched, so it leaks nothing.
        const code = error.response.data?.error.message
        if (code === 'EMAIL_NOT_VERIFIED') {
          setNeedsVerification(true)
          setServerError('Devi prima confermare il tuo indirizzo email: apri il link che ti abbiamo mandato.')
        } else {
          setServerError(
            code === 'ACCOUNT_REJECTED'
              ? 'La tua registrazione non è stata approvata.'
              : 'Il tuo account è in attesa di approvazione. Riceverai un’email appena sarà attivo.',
          )
        }
      } else {
        setServerError('Si è verificato un errore. Riprova.')
      }
    }
  }

  async function resendVerification() {
    // Uniform on the server whether or not the address exists, so we can say "sent" regardless.
    await authApi.resendVerification(getValues('email')).catch(() => undefined)
    setResent(true)
  }

  return (
    <AuthLayout title="Accedi al tuo account" subtitle="Accedi per vedere conti, piano e portafoglio.">
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

        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <PasswordInput
            id="password"
            autoComplete="current-password"
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? 'password-msg' : undefined}
            className="min-h-12"
            {...register('password')}
          />
        </Field>

        <Link to="/password-dimenticata" className="link -mt-2 self-start text-[14px]">
          Password dimenticata?
        </Link>

        {serverError && <ErrorBlock>{serverError}</ErrorBlock>}
        {needsVerification && (
          <Button onClick={resendVerification} disabled={resent}>
            {resent ? 'Email inviata' : 'Reinvia email di conferma'}
          </Button>
        )}

        <Button type="submit" variant="primary" disabled={isSubmitting} className="mt-1 min-h-[50px] text-[16px] font-extrabold">
          {isSubmitting ? 'Accesso in corso…' : 'Accedi'}
        </Button>
      </form>

      <p className="mt-5 text-center text-[14px] text-ink-2">
        Non hai un account?{' '}
        <Link to="/register" className="link">
          Registrati
        </Link>
      </p>
    </AuthLayout>
  )
}
