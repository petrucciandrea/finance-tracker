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

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) })

  async function onSubmit(values: LoginFormValues) {
    setServerError(null)
    try {
      await login(values)
      navigate('/', { replace: true })
    } catch (error) {
      // Same message the backend intentionally uses for both "unknown
      // email" and "wrong password" — don't try to be more specific here,
      // that would defeat the point of the backend's choice.
      if (isAxiosError<ApiErrorResponse>(error) && error.response?.status === 401) {
        setServerError('Email o password non corretti')
      } else {
        setServerError('Si è verificato un errore. Riprova.')
      }
    }
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

        {serverError && <ErrorBlock>{serverError}</ErrorBlock>}

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
