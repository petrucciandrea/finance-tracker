import type { ReactNode } from 'react'

export type StatusKind = 'ok' | 'warn' | 'over' | 'good' | 'info'

const KINDS: Record<StatusKind, string> = {
  ok: 'bg-card-2 text-ink-2',
  warn: 'bg-warn-soft text-warn',
  over: 'bg-neg-soft text-neg',
  good: 'bg-pos-soft text-pos',
  info: 'bg-accent-soft text-accent',
}

/** Status pill. The text carries the meaning; colour only reinforces it. */
export function StatusChip({ kind = 'ok', children, className = '' }: { kind?: StatusKind; children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-extrabold whitespace-nowrap tabular-nums ${KINDS[kind]} ${className}`}
    >
      {children}
    </span>
  )
}
