import { toISODate } from '@/lib/format'

export function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

export function endOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0)
}

export function addMonths(date: Date, months: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + months, 1)
}

export function monthRange(date: Date): { date_from: string; date_to: string } {
  return { date_from: toISODate(startOfMonth(date)), date_to: toISODate(endOfMonth(date)) }
}

export function isSameMonth(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()
}

/**
 * Share of the month elapsed by `today`, as a percentage — the "expected
 * pace" tick on spend bars. A closed month is 100; a future one 0.
 */
export function monthPace(month: Date, today: Date): number {
  if (month > today && !isSameMonth(month, today)) return 0
  if (!isSameMonth(month, today)) return 100
  return (today.getDate() / endOfMonth(today).getDate()) * 100
}
