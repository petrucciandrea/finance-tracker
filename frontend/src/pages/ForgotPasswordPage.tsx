import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { requestPasswordReset } from '@/api/auth'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { ErrorBlock, Notice } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'

const schema = z.object({ email: z.string().email('Inserisci un indirizzo email valido') })
type Values = z.infer<typeof schema>

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  async function onSubmit({ email }: Values) {
    setError(null)
    try {
      await requestPasswordReset(email)
      setSent(true)
    } catch (e) {
      setError(
        isAxiosError(e) && e.response?.status === 429
          ? 'Troppi tentativi. Riprova tra qualche minuto.'
          : 'Si è verificato un errore. Riprova.',
      )
    }
  }

  return (
    <AuthLayout title="Password dimenticata" subtitle="Ti mandiamo un link per sceglierne una nuova.">
      {sent ? (
        <div className="mt-6 flex flex-col gap-4">
          <Notice tone="info">Controlla la tua email</Notice>
          <p className="text-[15px] text-ink-2">
            Se esiste un account con questo indirizzo, tra poco riceverai un link per reimpostare la password. Vale 60
            minuti e funziona una sola volta.
          </p>
        </div>
      ) : (
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
          {error && <ErrorBlock>{error}</ErrorBlock>}
          <Button type="submit" variant="primary" disabled={isSubmitting} className="min-h-[50px] text-[16px] font-extrabold">
            {isSubmitting ? 'Invio…' : 'Invia il link'}
          </Button>
        </form>
      )}
      <p className="mt-5 text-center text-[14px] text-ink-2">
        <Link to="/login" className="link">
          Torna all&apos;accesso
        </Link>
      </p>
    </AuthLayout>
  )
}
