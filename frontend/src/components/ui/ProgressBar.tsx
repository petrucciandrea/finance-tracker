import type { StatusKind } from '@/components/ui/StatusChip'

const FILLS: Record<StatusKind, string> = {
  ok: 'bg-bar',
  warn: 'bg-warn',
  over: 'bg-neg',
  good: 'bg-pos',
  info: 'bg-accent',
}

interface ProgressBarProps {
  // 0–100+; the fill is clamped, the label carries the real figure.
  value: number
  kind?: StatusKind
  // Where spending "should" be by today, as a % of the period. Drawn as a
  // tick across the track; omitted where the logic is inverted (savings).
  pace?: number | null
  label: string
  thick?: boolean
}

export function ProgressBar({ value, kind = 'ok', pace, label, thick = false }: ProgressBarProps) {
  const width = Math.max(0, Math.min(value, 100))
  return (
    <div role="img" aria-label={label} className={`relative rounded-full bg-track ${thick ? 'h-2' : 'h-1.5'}`}>
      <span className={`absolute inset-y-0 left-0 rounded-full ${FILLS[kind]}`} style={{ width: `${width}%` }} />
      {pace != null && (
        <span
          className="absolute -top-1 -bottom-1 w-0.5 rounded-[1px] bg-ink"
          style={{ left: `${Math.max(0, Math.min(pace, 100))}%` }}
        />
      )}
    </div>
  )
}
