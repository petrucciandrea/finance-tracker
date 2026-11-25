import { formatFullDate, formatMoney } from '@/lib/format'
import type { Alert } from '@/types'

const money = (value: string | null, currency: string | null) => (value === null ? '' : formatMoney(value, currency ?? 'EUR'))
const on = (date: string | null) => (date ? formatFullDate(date) : '')

/**
 * The sentence for an alert. Worded here rather than by the backend so the
 * amounts go through formatMoney and "Nascondi importi" masks them.
 */
export function alertText(a: Alert): { title: string; body: string } {
  switch (a.kind) {
    case 'account_short':
      return {
        title: `${a.account_name}: non basta per gli addebiti programmati`,
        body: `Sul conto ci sono ${money(a.balance, a.currency)}, ne usciranno ${money(a.committed, a.currency)} (il primo il ${on(a.due_date)}: ${a.label}). Porta liquidità sul conto prima della scadenza.`,
      }
    case 'account_near':
      return {
        title: `${a.account_name}: margine stretto sugli addebiti programmati`,
        body: `Il saldo copre i ${money(a.committed, a.currency)} in uscita con meno di ${money(a.margin, a.currency)} di margine (il primo il ${on(a.due_date)}: ${a.label}). Meglio lasciare la liquidità sul conto.`,
      }
    case 'f24_overdue':
      return {
        title: `F24 scaduto il ${on(a.due_date)}`,
        body: `${a.label} · ${money(a.amount, a.currency)}. Né pagato né programmato: se l'hai già versato, registralo in Fatture.`,
      }
    case 'f24_upcoming':
      return {
        title: `F24 in scadenza il ${on(a.due_date)}`,
        body: `${a.label} · ${money(a.amount, a.currency)}. Pagalo o programma l'addebito, e registralo in Fatture.`,
      }
    case 'scheduled_unconfirmed':
      return {
        title: `Addebito del ${on(a.due_date)} da confermare`,
        body: `${a.label} · ${money(a.amount, a.currency)}${a.account_name ? ` su ${a.account_name}` : ''}. Controlla che sia uscito dal conto e confermalo in Fatture: fino ad allora non conta come pagato.`,
      }
    case 'vehicle_overdue':
      return {
        title: `Scaduto il ${on(a.due_date)}`,
        body: `${a.label}${a.amount ? ` · ${money(a.amount, a.currency)}` : ''}. Se l'hai già fatto, segnalo come fatto in Beni.`,
      }
    case 'vehicle_upcoming':
      return {
        title: `In scadenza il ${on(a.due_date)}`,
        body: `${a.label}${a.amount ? ` · ${money(a.amount, a.currency)}` : ''}.`,
      }
  }
}
