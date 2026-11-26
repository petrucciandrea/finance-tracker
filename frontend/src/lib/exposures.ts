import type { ExposureDimension, ExposureSource } from '@/types'

export const DIMENSION_LABELS: Record<ExposureDimension, string> = {
  asset_class: 'Asset class',
  region: 'Aree',
  sector: 'Settori',
  currency: 'Valute',
}

// Mirrors EXPOSURE_BUCKETS in the backend schemas (order = the editor's).
export const BUCKET_LABELS: Record<ExposureDimension, Record<string, string>> = {
  asset_class: {
    equity: 'Azionario',
    bond: 'Obbligazionario',
    money_market: 'Monetario',
    commodity: 'Materie prime e oro',
    crypto: 'Crypto',
    real_estate: 'Immobiliare',
    other: 'Altro',
  },
  region: {
    north_america: 'Nord America',
    europe_ex_italy: 'Europa (esclusa Italia)',
    italy: 'Italia',
    united_kingdom: 'Regno Unito',
    japan: 'Giappone',
    pacific_ex_japan: 'Pacifico (escluso Giappone)',
    emerging: 'Mercati emergenti',
    not_applicable: 'Non applicabile',
  },
  sector: {
    information_technology: 'Tecnologia',
    financials: 'Finanza',
    health_care: 'Salute',
    consumer_discretionary: 'Beni voluttuari',
    communication_services: 'Comunicazioni',
    industrials: 'Industria',
    consumer_staples: 'Beni di prima necessità',
    energy: 'Energia',
    materials: 'Materiali',
    utilities: 'Servizi pubblici',
    real_estate: 'Immobiliare',
  },
  currency: { EUR: 'Euro', USD: 'Dollaro USA', GBP: 'Sterlina', JPY: 'Yen', CHF: 'Franco svizzero', other: 'Altre' },
}

export function bucketLabel(dimension: ExposureDimension, bucket: string): string {
  if (bucket === 'cash') return 'Liquidità'
  return BUCKET_LABELS[dimension][bucket] ?? bucket
}

export const SOURCE_LABELS: Record<ExposureSource, string> = {
  user: 'tuoi dati',
  reference: 'dati precaricati',
  default: 'dal tipo',
}

// Weights dated more than a year ago are flagged (index weights drift).
export function isStale(asOf: string | null, today = new Date()): boolean {
  if (!asOf) return false
  const days = (today.getTime() - new Date(asOf).getTime()) / 86_400_000
  return days > 365
}
