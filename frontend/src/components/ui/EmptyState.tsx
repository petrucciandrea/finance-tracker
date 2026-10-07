import type { ReactNode } from 'react'

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-[12px] border border-dashed border-field px-6 py-10 text-center">
      <p className="text-[15px] font-extrabold text-ink">{title}</p>
      {children && <div className="max-w-md text-[14px] text-ink-2">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function LoadingBlock({ label = 'Caricamento…', className = 'h-32' }: { label?: string; className?: string }) {
  return (
    <div role="status" className={`flex items-center justify-center rounded-[12px] bg-card-2 text-[13px] font-semibold text-ink-3 ${className}`}>
      {label}
    </div>
  )
}

export function ErrorBlock({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-[10px] bg-neg-soft px-3 py-2 text-[13px] font-bold text-neg">
      {children}
    </p>
  )
}

/** Amber notice: attention, not error (to classify, possible duplicates, …). */
export function Notice({ children, action, tone = 'warn' }: { children: ReactNode; action?: ReactNode; tone?: 'warn' | 'info' }) {
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-[10px] px-3 py-2 text-[13px] font-bold tabular-nums ${
        tone === 'warn' ? 'bg-warn-soft text-warn' : 'bg-accent-soft text-accent'
      }`}
    >
      <span>{children}</span>
      {action}
    </div>
  )
}
