// Kept in sync with the currencies seeded in the backend (see the
// 0002_seed_currencies migration) — a fixed list avoids free-text typos
// that would 422 against the currency FK check anyway.
export const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'] as const

export type CurrencyCode = (typeof CURRENCIES)[number]

export const CURRENCY_NAMES: Record<CurrencyCode, string> = {
  EUR: 'Euro',
  USD: 'Dollaro statunitense',
  GBP: 'Sterlina',
  CHF: 'Franco svizzero',
  JPY: 'Yen',
}
