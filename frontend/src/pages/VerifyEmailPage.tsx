import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { verifyEmail } from '@/api/auth'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import { readHashToken } from '@/lib/hashToken'

/**
 * Landing page of the confirmation link. The call is idempotent, so running it
 * on load (even twice, under StrictMode) is harmless.
 */
export function VerifyEmailPage() {
  const [token] = useState(readHashToken)
  const [state, setState] = useState<'working' | 'ok' | 'failed'>(token ? 'working' : 'failed')

  useEffect(() => {
    if (!token) return
    verifyEmail(token)
      .then(() => setState('ok'))
      .catch(() => setState('failed'))
  }, [token])

  return (
    <AuthLayout title="Conferma email" subtitle="Verifichiamo il tuo indirizzo.">
      <div className="mt-6 flex flex-col gap-4">
        {state === 'working' && <LoadingBlock label="Verifica in corso…" />}
        {state === 'ok' && (
          <>
            <Notice tone="info">Indirizzo confermato</Notice>
            <Link to="/login" className="link">
              Vai al login
            </Link>
          </>
        )}
        {state === 'failed' && (
          <>
            <ErrorBlock>Link non valido o scaduto.</ErrorBlock>
            <p className="text-[15px] text-ink-2">
              Prova ad accedere: se l&apos;indirizzo non è ancora confermato potrai chiedere un nuovo link.
            </p>
            <Link to="/login" className="link">
              Vai al login
            </Link>
          </>
        )}
      </div>
    </AuthLayout>
  )
}
