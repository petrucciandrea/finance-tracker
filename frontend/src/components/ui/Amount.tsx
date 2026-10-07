import { formatAmount, toNumber, type SignMode } from '@/lib/format'

export type AmountKind = 'income' | 'expense' | 'transfer' | 'neutral'

interface AmountProps {
  value: string | number
  currency: string
  // Same amount in the user's base currency. Shown underneath as "≈ …" only
  // when the currencies differ.
  baseValue?: string | number
  baseCurrency?: string
  // income → green with "+"; expense → neutral ink with "−" (spending isn't
  // an error); transfer → muted with ⇄ and no sign.
  kind?: AmountKind
  className?: string
  align?: 'left' | 'right'
}

const COLORS: Record<AmountKind, string> = {
  income: 'text-pos',
  expense: 'text-ink',
  transfer: 'text-ink-3',
  neutral: 'text-ink',
}

export function Amount({
  value,
  currency,
  baseValue,
  baseCurrency,
  kind = 'neutral',
  className = 'font-extrabold',
  align = 'right',
}: AmountProps) {
  const sign: SignMode = kind === 'income' ? 'always' : kind === 'transfer' ? 'never' : 'auto'
  // Expenses are stored negative already; force the minus if one arrives
  // positive so the sign always matches the type.
  const shown = kind === 'expense' ? -Math.abs(toNumber(value)) : value
  const converted = baseValue !== undefined && baseCurrency && baseCurrency !== currency
  const shownBase = kind === 'expense' ? -Math.abs(toNumber(baseValue)) : baseValue

  return (
    <span className={`inline-flex flex-col tabular-nums whitespace-nowrap ${align === 'right' ? 'items-end' : 'items-start'}`}>
      <span className={`${COLORS[kind]} ${className}`}>
        {kind === 'transfer' && <span aria-label="trasferimento">⇄ </span>}
        {formatAmount(shown, currency, { sign })} <span className="ccy">{currency}</span>
      </span>
      {converted && (
        <span className="text-[12px] font-medium text-ink-3">
          ≈ {formatAmount(shownBase, baseCurrency, { sign: kind === 'transfer' ? 'never' : sign })} {baseCurrency}
        </span>
      )}
    </span>
  )
}

/** A change with direction arrow: "▲ +1.284,10" / "▼ −3,2%". Colour plus arrow, never colour alone. */
export function Delta({
  value,
  currency,
  percent,
  className = '',
}: {
  value: number
  currency?: string
  percent?: number | null
  className?: string
}) {
  const up = value > 0
  const flat = value === 0
  const color = flat ? 'text-ink-3' : up ? 'text-pos' : 'text-neg'
  const parts: string[] = []
  if (currency !== undefined) parts.push(formatAmount(value, currency, { sign: 'always' }))
  if (percent !== undefined && percent !== null) {
    parts.push(`${percent > 0 ? '+' : percent < 0 ? '−' : ''}${Math.abs(percent).toLocaleString('it-IT', { maximumFractionDigits: 1 })}%`)
  }
  return (
    <span className={`font-extrabold tabular-nums ${color} ${className}`}>
      <span aria-hidden="true">{flat ? '' : up ? '▲ ' : '▼ '}</span>
      <span className="sr-only">{flat ? '' : up ? 'in aumento ' : 'in calo '}</span>
      {parts.join(' · ')}
    </span>
  )
}
