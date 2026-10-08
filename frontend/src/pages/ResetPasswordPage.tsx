import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { confirmPasswordReset } from '@/api/auth'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { ErrorBlock, Notice } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { readHashToken } from '@/lib/hashToken'

const schema = z
  .object({
    new_password: z.string().min(8, 'Almeno 8 caratteri'),
    confirm_password: z.string().min(1, 'Conferma la nuova password'),
  })
  .refine((v) => v.new_password === v.confirm_password, {
    message: 'Le due password non coincidono',
    path: ['confirm_password'],
  })
type Values = z.infer<typeof schema>

export function ResetPasswordPage() {
  const [token] = useState(readHashToken)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(token ? null : 'Link non valido.')
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  async function onSubmit(values: Values) {
    if (!token) return
    setError(null)
    try {
      await confirmPasswordReset(token, values.new_password)
      setDone(true)
    } catch (e) {
      setError(
        isAxiosError(e) && e.response?.status === 401
          ? 'Link non valido, scaduto o già usato. Chiedine uno nuovo.'
          : 'Si è verificato un errore. Riprova.',
      )
    }
  }

  return (
    <AuthLayout title="Nuova password" subtitle="Scegli la password con cui accederai da ora.">
      {done ? (
        <div className="mt-6 flex flex-col gap-4">
          <Notice tone="info">Password aggiornata</Notice>
          <p className="text-[15px] text-ink-2">Le sessioni aperte sugli altri dispositivi sono state chiuse.</p>
          <Link to="/login" className="link">
            Vai al login
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} className="mt-6 flex flex-col gap-[18px]" noValidate>
          <Field label="Nuova password" htmlFor="new_password" error={errors.new_password?.message} hint="Almeno 8 caratteri.">
            <PasswordInput id="new_password" autoComplete="new-password" className="min-h-12" {...register('new_password')} />
          </Field>
          <Field label="Conferma nuova password" htmlFor="confirm_password" error={errors.confirm_password?.message}>
            <PasswordInput id="confirm_password" autoComplete="new-password" className="min-h-12" {...register('confirm_password')} />
          </Field>
          {error && <ErrorBlock>{error}</ErrorBlock>}
          <Button type="submit" variant="primary" disabled={isSubmitting || !token} className="min-h-[50px] text-[16px] font-extrabold">
            {isSubmitting ? 'Salvataggio…' : 'Imposta la password'}
          </Button>
          {error && (
            <Link to="/password-dimenticata" className="link text-center text-[14px]">
              Chiedi un nuovo link
            </Link>
          )}
        </form>
      )}
    </AuthLayout>
  )
}
