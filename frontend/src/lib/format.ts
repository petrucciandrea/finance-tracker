/**
 * The one place amounts, percentages and dates are turned into text.
 *
 * Amounts come from the API as Decimal strings; Number() is only for display
 * here, never for arithmetic that gets sent back. The currency is always a
 * parameter — callers pass `user.base_currency` for totals and the row's own
 * currency for original amounts, never a hard-coded code.
 */

const LOCALE = 'it-IT'

// U+2212: same width as "+" in tabular figures, unlike the hyphen Intl emits.
export const MINUS = '−'

const numberFormats = new Map<string, Intl.NumberFormat>()

function fractionDigits(currency: string | undefined): number {
  if (!currency) return 2
  try {
    return new Intl.NumberFormat(LOCALE, { style: 'currency', currency }).resolvedOptions()
      .maximumFractionDigits ?? 2
  } catch {
    // Unknown code (e.g. a crypto ticker): fall back to cents.
    return 2
  }
}

function numberFormat(minDigits: number, maxDigits: number): Intl.NumberFormat {
  const key = `${minDigits}:${maxDigits}`
  let nf = numberFormats.get(key)
  if (!nf) {
    // 'always': it-IT otherwise skips the separator on 4-digit numbers
    // ("1234,56"), so a column of amounts wouldn't line up.
    nf = new Intl.NumberFormat(LOCALE, {
      minimumFractionDigits: minDigits,
      maximumFractionDigits: maxDigits,
      useGrouping: 'always',
    })
    numberFormats.set(key, nf)
  }
  return nf
}

export function toNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : 0
}

export type SignMode = 'auto' | 'always' | 'never'

/**
 * "1.234,56" with the currency's own number of decimals. The code itself is
 * rendered separately (small, grey) by <Amount>, so it is not included here.
 * `sign: 'always'` prints "+" on positives (incomes, gains); 'never' drops
 * the sign entirely (a transfer shows ⇄ instead).
 */
export function formatAmount(
  value: string | number | null | undefined,
  currency?: string,
  { sign = 'auto', digits }: { sign?: SignMode; digits?: number } = {},
): string {
  const n = toNumber(value)
  const d = digits ?? fractionDigits(currency)
  const body = numberFormat(d, d).format(Math.abs(n))
  if (sign === 'never' || n === 0) return body
  if (n < 0) return `${MINUS}${body}`
  return sign === 'always' ? `+${body}` : body
}

/** Amount followed by its code, for plain-text contexts (aria-labels, tooltips). */
export function formatMoney(
  value: string | number | null | undefined,
  currency: string,
  options?: { sign?: SignMode },
): string {
  return `${formatAmount(value, currency, options)} ${currency}`
}

/** Compact axis label: "85k", "1,2 Mln". */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat(LOCALE, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

/** Quantities (shares, crypto units): up to 8 decimals, no trailing zeros. */
export function formatQuantity(value: string | number): string {
  return numberFormat(0, 8).format(toNumber(value))
}

/** "64,7%". `sign: 'always'` for changes ("+1,5%"). */
export function formatPercent(
  value: number | null | undefined,
  { digits = 1, sign = 'auto' }: { digits?: number; sign?: SignMode } = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const body = numberFormat(0, digits).format(Math.abs(value))
  if (sign === 'never' || value === 0) return `${body}%`
  if (value < 0) return `${MINUS}${body}%`
  return sign === 'always' ? `+${body}%` : `${body}%`
}

// --- Dates ---

/** "YYYY-MM-DD" → a local Date. `new Date(iso)` would parse it as UTC and
    show the previous day west of Greenwich. */
export function parseISODate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, (m ?? 1) - 1, d ?? 1)
}

/** Local date → "YYYY-MM-DD" (toISOString would shift it to UTC). */
export function toISODate(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function asDate(value: string | Date): Date {
  return typeof value === 'string' ? parseISODate(value) : value
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const shortDate = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short' })
const longDate = new Intl.DateTimeFormat(LOCALE, { weekday: 'long', day: 'numeric', month: 'long' })
const fullDate = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'long', year: 'numeric' })
const monthYear = new Intl.DateTimeFormat(LOCALE, { month: 'long', year: 'numeric' })
const monthLong = new Intl.DateTimeFormat(LOCALE, { month: 'long' })
const monthShort = new Intl.DateTimeFormat(LOCALE, { month: 'short' })
const weekdayShort = new Intl.DateTimeFormat(LOCALE, { weekday: 'short' })

/** "6 ott" */
export const formatShortDate = (value: string | Date) => shortDate.format(asDate(value))
/** "Martedì 6 ottobre" */
export const formatLongDate = (value: string | Date) => capitalize(longDate.format(asDate(value)))
/** "6 ottobre 2026" */
export const formatFullDate = (value: string | Date) => fullDate.format(asDate(value))
/** "Ottobre 2026" */
export const formatMonthYear = (value: string | Date) => capitalize(monthYear.format(asDate(value)))
/** "ottobre" */
export const formatMonthName = (value: string | Date) => monthLong.format(asDate(value))
/** "ott" */
export const formatMonthShort = (value: string | Date) => monthShort.format(asDate(value)).replace('.', '')
/** "Mar 6 ottobre" — day-group headers. */
export function formatDayHeader(value: string | Date): string {
  const date = asDate(value)
  const weekday = capitalize(weekdayShort.format(date).replace('.', ''))
  return `${weekday} ${date.getDate()} ${monthLong.format(date)}`
}

/** Initials for the avatar: first + last name, else the email's first letters. */
export function initials(firstName: string | null, lastName: string | null, email: string): string {
  const fromName = `${firstName?.trim().charAt(0) ?? ''}${lastName?.trim().charAt(0) ?? ''}`
  if (fromName) return fromName.toUpperCase()
  return email.slice(0, 2).toUpperCase()
}

/** "Andrea P." when there's a name, else the email. */
export function displayName(firstName: string | null, lastName: string | null, email: string): string {
  const first = firstName?.trim()
  const last = lastName?.trim()
  if (first && last) return `${first} ${last.charAt(0)}.`
  return first || last || email
}
