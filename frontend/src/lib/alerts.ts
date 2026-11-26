import { bucketLabel } from '@/lib/exposures'
import { formatFullDate, formatMoney, formatMonthYear, formatPercent } from '@/lib/format'
import type { Alert, ExposureDimension } from '@/types'

const pct = (value: number | null) => (value === null ? '' : formatPercent(value, { digits: 0 }))
// What a rule is about: a bucket of a dimension, or a product (label = symbol).
function subject(a: Alert): string {
  if (a.dimension === 'position') return a.label
  if (a.dimension && a.bucket) return bucketLabel(a.dimension as ExposureDimension, a.bucket)
  return a.label
}

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
    case 'goal_overdue':
      return {
        title: `«${a.label}»: scadenza passata`,
        body: `Era per il ${on(a.due_date)} e mancano ancora ${money(a.amount, a.currency)}. Sposta la data o segnalo come raggiunto nel Piano.`,
      }
    case 'goal_due_soon':
      return {
        title: `«${a.label}» scade il ${on(a.due_date)}`,
        body: `Mancano ancora ${money(a.amount, a.currency)} al target.`,
      }
    case 'goal_behind_schedule':
      return {
        title: `«${a.label}» è in ritardo`,
        body: `Dal mese prossimo servono ${money(a.amount, a.currency)} al mese per arrivare in tempo${a.due_date ? `; con la sola quota mensile arriva a ${formatMonthYear(a.due_date)}` : '; con la sola quota mensile non arriva'}. Puoi dargli più priorità nel suo pilastro o alzare la quota di risparmio.`,
      }
    case 'goal_horizon_mismatch':
      return {
        title: `«${a.label}»: scadenza vicina, investimento volatile`,
        body: `Scade il ${on(a.due_date)} ma il ${pct(a.percentage)} di quanto c'è è in azioni o crypto: un calo nell'ultimo periodo non si recupera in tempo.`,
      }
    case 'allocation_out_of_band':
      return {
        title: `${subject(a)}: fuori dal target che ti sei dato`,
        body: `È al ${pct(a.percentage)} contro un target del ${pct(a.limit_percentage)}. Il Piano suggerisce come dividere i prossimi versamenti per rientrare senza vendere.`,
      }
    case 'allocation_over_cap':
      return {
        title: `${subject(a)}: sopra il limite che ti sei dato`,
        body: `È al ${pct(a.percentage)} degli investimenti, il limite è il ${pct(a.limit_percentage)}.`,
      }
    case 'excess_cash':
      return {
        title: 'Liquidità ferma oltre la soglia',
        body: `Tolti spese del mese, fondo emergenza e addebiti programmati restano ${money(a.amount, a.currency)} senza un compito, oltre i ${money(a.committed, a.currency)} che ti sei dato.`,
      }
    case 'below_min_invested_share':
      return {
        title: 'Quota investita sotto il minimo',
        body: `È investito il ${pct(a.percentage)} del patrimonio libero (esclusi fondo emergenza, accantonamenti e tasse), il minimo che ti sei dato è il ${pct(a.limit_percentage)}.`,
      }
    case 'investing_without_emergency_fund':
      return {
        title: 'Investimenti con il fondo emergenza incompleto',
        body: `Questo mese hai comprato investimenti mentre a «${a.label}» mancano ${money(a.amount, a.currency)}. Di solito si completa prima la riserva.`,
      }
    case 'exposure_data_stale':
      return {
        title: 'Composizione degli ETF da aggiornare',
        body: `${a.label} posizioni hanno pesi (aree, settori) di più di un anno fa. Aggiornali dal factsheet nel Portafoglio.`,
      }
  }
}
