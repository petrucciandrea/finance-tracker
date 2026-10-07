import type { MetalForm, PreciousMetal, VehicleType } from '@/types'

export const VEHICLE_TYPE_LABELS: Record<VehicleType, string> = {
  car: 'Auto',
  motorcycle: 'Moto',
  other: 'Altro veicolo',
}

export const METAL_LABELS: Record<PreciousMetal, string> = {
  gold: 'Oro',
  silver: 'Argento',
  platinum: 'Platino',
}

export const METAL_FORM_LABELS: Record<MetalForm, string> = {
  bullion: 'Lingotto',
  coin: 'Moneta',
  jewelry: 'Gioiello',
}

// Hallmarks as they're stamped on the object, in thousandths. Gold also
// goes by carats, so those are spelled out next to the fineness.
export const PURITY_PRESETS: Record<PreciousMetal, { value: string; label: string }[]> = {
  gold: [
    { value: '999.9', label: '999,9 · 24 kt (investimento)' },
    { value: '916', label: '916 · 22 kt (sterline, krugerrand)' },
    { value: '750', label: '750 · 18 kt' },
    { value: '585', label: '585 · 14 kt' },
    { value: '375', label: '375 · 9 kt' },
  ],
  silver: [
    { value: '999', label: '999 · investimento' },
    { value: '925', label: '925 · sterling' },
    { value: '800', label: '800' },
  ],
  platinum: [
    { value: '999.5', label: '999,5 · investimento' },
    { value: '950', label: '950' },
  ],
}

// A starting point, not advice: roughly what a mainstream car loses per
// year once past the first-year drop. The user can change it per vehicle.
export const DEFAULT_DEPRECIATION_PCT = '15'

/** "1.200,50" or "1200.50" → "1200.50" for the API. */
export function parseLocaleNumber(value: string): string {
  const trimmed = value.trim()
  if (trimmed.includes(',')) return trimmed.replace(/\./g, '').replace(',', '.')
  return trimmed
}

export function isLocaleNumber(value: string): boolean {
  return value.trim() !== '' && Number.isFinite(Number(parseLocaleNumber(value)))
}

/** Thousandths as typed ("750", "999,9") → the API's 0–1 fraction ("0.7500"). */
export function millesimiToPurity(value: string): string {
  return (Number(parseLocaleNumber(value)) / 1000).toFixed(4)
}

export function purityToMillesimi(purity: string): string {
  // Drop trailing zeros: 0.7500 → "750", 0.9999 → "999.9".
  return String(Number((Number(purity) * 1000).toFixed(1)))
}
