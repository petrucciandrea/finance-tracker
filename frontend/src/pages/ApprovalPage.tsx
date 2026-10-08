import { useEffect, useState } from 'react'
import { isAxiosError } from 'axios'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import * as authApi from '@/api/auth'
import { readHashToken } from '@/lib/hashToken'
import type { ApprovalRequestInfo } from '@/types'

const OUTCOME_LABEL = { approved: 'Account approvato', rejected: 'Registrazione rifiutata' } as const

/**
 * Where the admin lands from the "new registration" email. The token is read
 * from the URL hash (never sent to a server) and opening the page changes
 * nothing: the decision is an explicit click, so mail scanners that prefetch
 * links can't approve or reject anyone.
 */
export function ApprovalPage() {
  const [token] = useState(readHashToken)
  const [info, setInfo] = useState<ApprovalRequestInfo | null>(null)
  const [error, setError] = useState<string | null>(token ? null : 'Link non valido.')
  const [busy, setBusy] = useState(false)
  const [decided, setDecided] = useState(false)

  useEffect(() => {
    if (!token) return
    authApi
      .previewApproval(token)
      .then(setInfo)
      .catch((e) =>
        setError(
          isAxiosError(e) && e.response?.status === 401 ? 'Link non valido o scaduto.' : 'Richiesta non trovata.',
        ),
      )
  }, [token])

  async function decide(decision: 'approve' | 'reject') {
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      setInfo(await authApi.decideApproval(token, decision))
      setDecided(true)
    } catch (e) {
      setError(
        isAxiosError(e) && e.response?.status === 409
          ? 'Questa richiesta è già stata gestita.'
          : 'Si è verificato un errore. Riprova.',
      )
    } finally {
      setBusy(false)
    }
  }

  const pending = info?.approval_status === 'pending'

  return (
    <AuthLayout title="Richiesta di registrazione" subtitle="Decidi se far entrare questo account.">
      <div className="mt-6 flex flex-col gap-4">
        {error && <ErrorBlock>{error}</ErrorBlock>}
        {!info && !error && <LoadingBlock />}

        {info && (
          <>
            <p className="text-[15px] text-ink-2">
              <strong className="text-ink">{info.email}</strong> ha chiesto di registrarsi il{' '}
              {new Date(info.created_at).toLocaleDateString('it-IT')}.
            </p>

            {pending ? (
              <div className="flex gap-3">
                <Button variant="primary" disabled={busy} onClick={() => decide('approve')} className="min-h-[50px] flex-1 font-extrabold">
                  Approva
                </Button>
                <Button variant="danger" disabled={busy} onClick={() => decide('reject')} className="min-h-[50px] flex-1 font-extrabold">
                  Rifiuta
                </Button>
              </div>
            ) : (
              <Notice tone={decided ? 'info' : 'warn'}>
                {decided ? OUTCOME_LABEL[info.approval_status as keyof typeof OUTCOME_LABEL] : 'Già gestita'}
              </Notice>
            )}
          </>
        )}
      </div>
    </AuthLayout>
  )
}
