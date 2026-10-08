import { parseLocaleNumber } from '@/lib/physicalAssets'
import type { TaxComponent, TaxPaymentKind, WorkType } from '@/types'

export const WORK_TYPE_LABELS: Record<WorkType, string> = {
  employee: 'Dipendente',
  flat_rate: 'P.IVA forfettaria',
  ordinary: 'P.IVA ordinaria',
}

export const TAX_COMPONENT_LABELS: Record<TaxComponent, string> = {
  substitute_tax: 'Imposta sostitutiva',
  inps: 'INPS',
}

export const TAX_KIND_LABELS: Record<TaxPaymentKind, string> = {
  balance: 'Saldo',
  first_advance: '1° acconto',
  second_advance: '2° acconto',
}

// Coefficienti di redditività by ATECO group.
export const COEFFICIENTS = [
  { value: '0.4000', label: '40% · commercio alimentare e bevande' },
  { value: '0.5400', label: '54% · commercio ambulante non alimentare' },
  { value: '0.6200', label: '62% · intermediari del commercio' },
  { value: '0.6700', label: '67% · altre attività economiche' },
  { value: '0.7800', label: '78% · professioni, scienze, istruzione, sanità' },
  { value: '0.8600', label: '86% · costruzioni e attività immobiliari' },
]

export const TAX_RATES = [
  { value: '0.0500', label: '5% · primi 5 anni di attività' },
  { value: '0.1500', label: '15% · aliquota ordinaria' },
]

export const REVENUE_LIMIT = 85000
// Must match services/flat_rate.py: STAMP_DUTY_*.
const STAMP_DUTY_THRESHOLD = 77.47
const STAMP_DUTY_AMOUNT = 2

/** "0.2623" → "26,23" for an input; trailing zeros dropped. */
export function rateToPercentInput(rate: string | null | undefined): string {
  if (rate === null || rate === undefined || rate === '') return ''
  return String(Number((Number(rate) * 100).toFixed(2))).replace('.', ',')
}

/** "26,23" → "0.2623" for the API. */
export function percentInputToRate(value: string): string {
  return (Number(parseLocaleNumber(value)) / 100).toFixed(4)
}

export function isPercentInput(value: string, { max = 100 }: { max?: number } = {}): boolean {
  if (value.trim() === '') return false
  const n = Number(parseLocaleNumber(value))
  return Number.isFinite(n) && n >= 0 && n <= max
}

export function autoStampDuty(amount: number, rivalsaRate: number): boolean {
  return amount + Math.round(amount * rivalsaRate * 100) / 100 > STAMP_DUTY_THRESHOLD
}

export interface InvoicePreview {
  rivalsa: number
  stamp: number
  total: number
  taxableBase: number
  substituteTax: number
  inps: number
  toProvision: number
}

/**
 * The per-invoice arithmetic, for the form's live preview only — the
 * figures shown everywhere else come from the server
 * (services/flat_rate.py:invoice_breakdown).
 */
export function previewInvoice({
  amount,
  rivalsaRate,
  stampDuty,
  coefficient,
  taxRate,
  inpsRate,
  provisionRate,
}: {
  amount: number
  rivalsaRate: number
  stampDuty: boolean
  coefficient: number
  taxRate: number
  inpsRate: number
  provisionRate: number
}): InvoicePreview {
  const rivalsa = Math.round(amount * rivalsaRate * 100) / 100
  const stamp = stampDuty ? STAMP_DUTY_AMOUNT : 0
  const total = amount + rivalsa + stamp
  const taxableBase = total * coefficient
  return {
    rivalsa,
    stamp,
    total,
    taxableBase,
    substituteTax: taxableBase * taxRate,
    inps: taxableBase * inpsRate,
    toProvision: total * provisionRate,
  }
}
