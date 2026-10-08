import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { LEGAL, LEGAL_INCOMPLETE } from '@/lib/legal'

/** Plain reading page for the public legal texts (no login needed to read them). */
export function LegalLayout({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-h-screen px-4 py-10 sm:px-6">
      <article className="mx-auto max-w-[720px]">
        <Link to="/login" className="link text-[14px]">
          ← Torna all&apos;accesso
        </Link>
        <h1 className="mt-6 text-[28px] font-extrabold tracking-[-0.02em]">{title}</h1>
        <p className="mt-1 text-[13px] text-ink-3">
          Versione {LEGAL.version} · aggiornata il {LEGAL.updatedOn}
        </p>
        {LEGAL_INCOMPLETE && (
          <p role="alert" className="mt-4 rounded-[10px] bg-warn-soft px-3 py-2 text-[13px] font-bold text-warn">
            Dati del titolare non configurati (VITE_LEGAL_CONTROLLER, VITE_LEGAL_EMAIL): non pubblicare così.
          </p>
        )}
        <div className="mt-6 flex flex-col gap-4 text-[15px] leading-relaxed text-ink-2 [&_h2]:mt-4 [&_h2]:text-[18px] [&_h2]:font-extrabold [&_h2]:text-ink [&_li]:ml-5 [&_li]:list-disc [&_strong]:text-ink">
          {children}
        </div>
      </article>
    </div>
  )
}

export function Controller() {
  return (
    <>
      <strong>{LEGAL.controller || '[titolare non configurato]'}</strong>
      {LEGAL.address ? `, ${LEGAL.address}` : ''}
      {' — '}
      {LEGAL.email ? <a className="link" href={`mailto:${LEGAL.email}`}>{LEGAL.email}</a> : '[contatto non configurato]'}
    </>
  )
}
