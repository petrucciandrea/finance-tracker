import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { CollectDialog, InvoiceDialog, TaxPaymentDialog, type PaymentDraft } from '@/components/flat-rate/FlatRateDialogs'
import { YearPicker } from '@/components/flat-rate/YearPicker'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import { KpiStrip, type Kpi } from '@/components/ui/KpiStrip'
import { PageHeader } from '@/components/ui/PageHeader'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { RowMenu, type RowMenuItem } from '@/components/ui/RowMenu'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { StatusChip } from '@/components/ui/StatusChip'
import { useAccounts } from '@/hooks/useAccounts'
import { useAuth } from '@/hooks/useAuth'
import {
  useDeleteInvoice,
  useDeleteTaxPayment,
  useFlatRateSummary,
  useInvoices,
  useTaxPayments,
  useUncollectInvoice,
} from '@/hooks/useFlatRate'
import { apiErrorMessage } from '@/lib/apiError'
import { REVENUE_LIMIT, TAX_COMPONENT_LABELS, TAX_KIND_LABELS } from '@/lib/flatRate'
import { formatAmount, formatFullDate, formatPercent, formatQuantity, formatShortDate, toNumber } from '@/lib/format'
import type { F24Deadline, FlatRateSummary, Invoice, TaxPayment } from '@/types'

const EUR = 'EUR'
type Filter = 'all' | 'collected' | 'outstanding'

function Money({ value, currency = EUR, strong = false }: { value: string | number; currency?: string; strong?: boolean }) {
  return (
    <span className={`whitespace-nowrap tabular-nums ${strong ? 'font-extrabold' : ''}`}>
      {formatAmount(value, currency)} <span className="ccy">{currency}</span>
    </span>
  )
}

const pct = (rate: string | number, digits = 0) => formatPercent(toNumber(rate) * 100, { digits })

// ---------------------------------------------------------------------------
// Invoices table
// ---------------------------------------------------------------------------

function InvoiceStatusCell({ invoice, year, compact = false }: { invoice: Invoice; year: number; compact?: boolean }) {
  if (!invoice.collected_on) return <StatusChip kind="warn">Da incassare</StatusChip>
  const otherYear = invoice.fiscal_year !== year
  return (
    <span className="flex flex-col items-start gap-0.5">
      {/* In the table the column is already "Incasso": the date alone keeps
          the 15 columns within the page width without side-scrolling. */}
      <StatusChip kind={otherYear ? 'info' : 'good'}>
        {compact ? <span className="sr-only">Incassata il </span> : 'Incassata '}
        {formatShortDate(invoice.collected_on)}
      </StatusChip>
      {otherYear && <span className="text-[11px] text-ink-3">tassata nel {invoice.fiscal_year}</span>}
      {invoice.transaction_deleted && <span className="text-[11px] text-warn">movimento eliminato</span>}
    </span>
  )
}

// Tight horizontal padding: with 15 columns, px-2 alone pushed the table
// past the 1200px page width.
const TH = 'border-b border-line py-2 px-1.5 font-bold whitespace-nowrap'
const TD = 'border-b border-line py-2.5 px-1.5 whitespace-nowrap'

function InvoicesTable({ invoices, year, actions }: { invoices: Invoice[]; year: number; actions: (i: Invoice) => RowMenuItem[] }) {
  return (
    <>
      <div className="relative -mx-1.5 overflow-x-auto max-lg:hidden">
        <table className="w-full border-collapse text-[13px] tabular-nums">
          <thead>
            <tr className="text-[12px] text-ink-3">
              <th scope="col" className={`${TH} text-left`}>Data</th>
              <th scope="col" className={`${TH} text-left`}>Cliente</th>
              <th scope="col" className={`${TH} text-right`}>Importo</th>
              <th scope="col" className={`${TH} text-right`}>Rivalsa</th>
              <th scope="col" className={`${TH} text-right`}>Bollo</th>
              <th scope="col" className={`${TH} text-right`}>Totale</th>
              <th scope="col" className={`${TH} text-left`}>Incasso</th>
              <th scope="col" className={`${TH} text-right`}>Acc. %</th>
              <th scope="col" className={`${TH} text-right`}>Imponibile</th>
              <th scope="col" className={`${TH} text-right`}>Imposta</th>
              <th scope="col" className={`${TH} text-right`}>INPS</th>
              <th scope="col" className={`${TH} text-right`}>Acc. imposta</th>
              <th scope="col" className={`${TH} text-right`}>Acc. INPS</th>
              <th scope="col" className={`${TH} text-right`}>Da accantonare</th>
              <th scope="col" className={TH}>
                <span className="sr-only">Azioni</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((i) => (
              <tr key={i.id}>
                <td className={TD}>
                  <div>{formatShortDate(i.issue_date)}</div>
                  {i.number && <div className="text-[11px] text-ink-3">n. {i.number}</div>}
                </td>
                <td className={`${TD} max-w-[150px] truncate font-bold`} title={i.client}>
                  {i.client}
                </td>
                <td className={`${TD} text-right`}>{formatAmount(i.amount, EUR)}</td>
                <td className={`${TD} text-right text-ink-2`}>{toNumber(i.rivalsa_amount) ? formatAmount(i.rivalsa_amount, EUR) : '—'}</td>
                <td className={`${TD} text-right text-ink-2`}>{i.stamp_duty ? formatAmount(i.stamp_duty_amount, EUR) : '—'}</td>
                <td className={`${TD} text-right font-bold`}>{formatAmount(i.total, EUR)}</td>
                <td className={TD}>
                  <InvoiceStatusCell invoice={i} year={year} compact />
                </td>
                <td className={`${TD} text-right ${i.provision_rate !== null ? 'font-bold' : 'text-ink-2'}`}>{pct(i.applied_provision_rate)}</td>
                <td className={`${TD} text-right text-ink-2`}>{formatAmount(i.taxable_base, EUR)}</td>
                <td className={`${TD} text-right text-ink-2`}>{formatAmount(i.substitute_tax, EUR)}</td>
                <td className={`${TD} text-right text-ink-2`}>{formatAmount(i.inps, EUR)}</td>
                <td className={`${TD} text-right text-ink-2`}>{formatAmount(i.substitute_tax_advance, EUR)}</td>
                <td className={`${TD} text-right text-ink-2`}>{formatAmount(i.inps_advance, EUR)}</td>
                <td className={`${TD} text-right font-bold`}>{formatAmount(i.to_provision, EUR)}</td>
                <td className="border-b border-line py-1 pl-1">
                  <RowMenu label={`Azioni per la fattura a ${i.client}`} items={actions(i)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="lg:hidden">
        {invoices.map((i) => (
          <li key={i.id} className="flex items-center gap-3 border-t border-line py-3 tabular-nums first:border-t-0">
            <div className="min-w-0 flex-1">
              <div className="truncate text-[15px] font-extrabold">{i.client}</div>
              <div className="text-[12px] text-ink-3">
                {formatShortDate(i.issue_date)}
                {i.number ? ` · n. ${i.number}` : ''} · imposta {formatAmount(i.substitute_tax, EUR)} · INPS {formatAmount(i.inps, EUR)}
              </div>
              <div className="mt-1">
                <InvoiceStatusCell invoice={i} year={year} />
              </div>
            </div>
            <div className="flex-none text-right">
              <Money value={i.total} strong />
              <div className="text-[12px] text-ink-3">
                accantona {formatAmount(i.to_provision, EUR)} ({pct(i.applied_provision_rate)})
              </div>
            </div>
            <RowMenu label={`Azioni per la fattura a ${i.client}`} items={actions(i)} />
          </li>
        ))}
      </ul>
    </>
  )
}

// ---------------------------------------------------------------------------
// Year breakdown, deadlines, payments, provision
// ---------------------------------------------------------------------------

function Line({ label, value, hint, strong = false }: { label: string; value: string | number; hint?: string; strong?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 border-t border-line py-2 first:border-t-0 ${strong ? 'font-extrabold' : ''}`}>
      <span className="min-w-0">
        {label}
        {hint && <span className="block text-[12px] font-normal text-ink-3">{hint}</span>}
      </span>
      <Money value={value} />
    </div>
  )
}

function YearBreakdown({ summary }: { summary: FlatRateSummary }) {
  const f = summary.figures
  const p = summary.params
  return (
    <Card
      title={`Calcolo ${summary.year}`}
      meta={<span className="text-[13px] font-bold text-ink-3">sull'incassato al {formatFullDate(summary.as_of)}</span>}
      action={
        <Link to="/profile#lavoro" className="text-[13px] font-bold text-accent underline-offset-2 hover:underline">
          Parametri
        </Link>
      }
    >
      <p className="mt-1 text-[12px] text-ink-3">
        Coefficiente {pct(p.profitability_coefficient)} · imposta {pct(p.substitute_tax_rate)} · INPS {pct(p.inps_rate, 2)}
        {toNumber(p.rivalsa_rate) > 0 ? ` · rivalsa ${pct(p.rivalsa_rate)}` : ''}
      </p>
      <div className="mt-2 text-[14px]">
        <Line label="Ricavi incassati" value={f.revenue} hint="Compensi + rivalsa + bolli" />
        <Line label="Reddito imponibile" value={f.taxable_base} />
        <Line label="Contributi INPS" value={f.inps} />
        <Line
          label="Imposta sostitutiva"
          value={f.substitute_tax}
          hint={toNumber(f.inps_deducted) > 0 ? `Dedotti ${formatAmount(f.inps_deducted, EUR)} € di INPS versati nell'anno` : undefined}
        />
        <Line label="Tasse e contributi dell'anno" value={f.liability} strong />
        <Line label="Acconti dovuti per l'anno" value={f.advances_due} hint="Calcolati sull'anno precedente" />
        <Line label="Versato per l'anno" value={f.paid} />
        <Line label="Da accantonare sulle fatture" value={f.to_provision} hint={`Al ${pct(p.effective_provision_rate)}${p.provision_rate === null ? ' consigliato' : ''}, salvo eccezioni per fattura`} />
      </div>
    </Card>
  )
}

function deadlineLabel(d: F24Deadline): string {
  const kind = TAX_KIND_LABELS[d.kind]
  return `${kind} ${TAX_COMPONENT_LABELS[d.component].toLowerCase()} ${d.fiscal_year}`
}

function DeadlinesCard({ deadlines, onPay }: { deadlines: F24Deadline[]; onPay: (draft: PaymentDraft) => void }) {
  const dates = [...new Set(deadlines.map((d) => d.due_date))].sort()
  return (
    <Card title="Scadenze F24">
      {deadlines.length === 0 ? (
        <p className="mt-2 text-[13px] text-ink-3">Nessuna scadenza: non c'è ancora incassato su cui calcolarle.</p>
      ) : (
        dates.map((date) => {
          const rows = deadlines.filter((d) => d.due_date === date)
          const due = rows.reduce((s, d) => s + toNumber(d.amount_due), 0)
          const estimate = rows.some((d) => d.is_estimate)
          return (
            <div key={date} className="mt-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-[14px] font-extrabold">
                  {formatFullDate(date)} {estimate && <StatusChip kind="info">stima</StatusChip>}
                </h3>
                <Money value={due} strong />
              </div>
              <ul className="mt-1 text-[13px]">
                {rows.map((d) => {
                  const paid = toNumber(d.amount_paid)
                  const owed = toNumber(d.amount_due)
                  const settled = paid >= owed - 0.005
                  return (
                    <li key={`${d.fiscal_year}-${d.component}-${d.kind}`} className="flex items-center gap-2 border-t border-line py-1.5 tabular-nums">
                      <span className="min-w-0 flex-1">{deadlineLabel(d)}</span>
                      {paid > 0 && (
                        <StatusChip kind={settled ? 'good' : 'warn'}>
                          {settled ? 'versato' : `versati ${formatAmount(paid, EUR)}`}
                        </StatusChip>
                      )}
                      <Money value={owed} />
                      {!settled && (
                        <Button
                          size="sm"
                          onClick={() =>
                            onPay({
                              fiscal_year: d.fiscal_year,
                              component: d.component,
                              kind: d.kind,
                              amount: String(Math.max(owed - paid, 0)),
                              paid_on: d.due_date,
                            })
                          }
                        >
                          Registra
                        </Button>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })
      )}
    </Card>
  )
}

function PaymentsCard({
  payments,
  accountName,
  actions,
}: {
  payments: TaxPayment[]
  accountName: (id: string) => string
  actions: (p: TaxPayment) => RowMenuItem[]
}) {
  return (
    <Card title="Versamenti F24">
      {payments.length === 0 ? (
        <p className="mt-2 text-[13px] text-ink-3">Nessun versamento registrato per quest'anno.</p>
      ) : (
        <ul className="mt-2 text-[13px] tabular-nums">
          {payments.map((p) => (
            <li key={p.id} className="flex items-center gap-2 border-t border-line py-2 first:border-t-0">
              <div className="min-w-0 flex-1">
                <div className="font-bold">
                  {TAX_KIND_LABELS[p.kind]} {TAX_COMPONENT_LABELS[p.component].toLowerCase()} {p.fiscal_year}
                </div>
                <div className="text-[12px] text-ink-3">
                  {formatFullDate(p.paid_on)}
                  {p.account_id ? ` · da ${accountName(p.account_id)}` : ''}
                  {p.notes ? ` · ${p.notes}` : ''}
                </div>
              </div>
              <Money value={p.amount} />
              <RowMenu label="Azioni per il versamento" items={actions(p)} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function ProvisionCard({ summary, base }: { summary: FlatRateSummary; base: string }) {
  const sources = summary.provision.sources
  const gap = toNumber(summary.gap)
  return (
    <Card
      title="Accantonamento"
      action={
        <Link to="/profile#lavoro" className="text-[13px] font-bold text-accent underline-offset-2 hover:underline">
          Gestisci
        </Link>
      }
    >
      {sources.length === 0 ? (
        <div className="mt-3">
          <EmptyState title="Nessun conto di accantonamento">
            Scegli nel profilo i conti e i prodotti dove metti da parte tasse e contributi: il gap li confronta con quanto dovrai versare.
          </EmptyState>
        </div>
      ) : (
        <ul className="mt-2 text-[13px] tabular-nums">
          {sources.map((s) => (
            <li key={s.id} className="flex items-center gap-2 border-t border-line py-2 first:border-t-0">
              <div className="min-w-0 flex-1">
                <div className="truncate font-bold">{s.asset ? s.asset.symbol : s.account_name}</div>
                <div className="text-[12px] text-ink-3">
                  {s.asset
                    ? `${s.asset.name} in ${s.account_name}${s.quantity !== null ? ` · ${formatQuantity(s.quantity)} quote` : ''}`
                    : 'liquidità'}
                  {s.buyable_units ? ` · la liquidità del conto basta per ${s.buyable_units} ${s.buyable_units === 1 ? 'quota' : 'quote'}` : ''}
                </div>
              </div>
              {s.value_base_currency === null ? <span className="text-ink-3">n.d.</span> : <Money value={s.value_base_currency} currency={base} />}
            </li>
          ))}
          <li className="flex items-center justify-between gap-2 border-t border-line py-2 font-extrabold">
            <span>Totale accantonato</span>
            <Money value={summary.provision.total_base_currency} currency={base} />
          </li>
          <li className="flex items-center justify-between gap-2 border-t border-line py-2">
            <span>Da versare con gli F24</span>
            <Money value={summary.cash_requirement} />
          </li>
          <li className={`flex items-center justify-between gap-2 border-t border-line py-2 font-extrabold ${gap < 0 ? 'text-neg' : 'text-pos'}`}>
            <span>{gap < 0 ? 'Mancano' : 'Margine'}</span>
            <Money value={Math.abs(gap)} currency={base} />
          </li>
        </ul>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function InvoicesPage() {
  const { user } = useAuth()
  const base = user?.base_currency ?? EUR
  const [year, setYear] = useState(() => new Date().getFullYear())
  const [filter, setFilter] = useState<Filter>('all')
  const summary = useFlatRateSummary(year)
  const invoices = useInvoices(year)
  const payments = useTaxPayments(year)
  const { data: accounts } = useAccounts()
  const uncollect = useUncollectInvoice()
  const deleteInvoice = useDeleteInvoice()
  const deletePayment = useDeleteTaxPayment()

  const [editing, setEditing] = useState<{ invoice: Invoice | null } | null>(null)
  const [collecting, setCollecting] = useState<Invoice | null>(null)
  const [paying, setPaying] = useState<{ payment: TaxPayment | null; draft: PaymentDraft | null } | null>(null)
  const [deleting, setDeleting] = useState<{ kind: 'invoice'; item: Invoice } | { kind: 'payment'; item: TaxPayment } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  // The section is off: the data stays (and keeps counting in net worth),
  // but the page belongs to the work type that unlocks it.
  if (user && user.work_type !== 'flat_rate') return <Navigate to="/profile#lavoro" replace />

  const accountName = (id: string) => (accounts ?? []).find((a) => a.id === id)?.name ?? 'conto eliminato'
  const list = (invoices.data ?? []).filter((i) =>
    filter === 'all' ? true : filter === 'collected' ? i.collected_on !== null : i.collected_on === null,
  )

  function invoiceActions(invoice: Invoice): RowMenuItem[] {
    return [
      { label: 'Modifica', onSelect: () => setEditing({ invoice }) },
      invoice.collected_on === null
        ? { label: 'Segna come incassata', onSelect: () => setCollecting(invoice) }
        : {
            label: 'Annulla incasso',
            onSelect: async () => {
              setActionError(null)
              try {
                await uncollect.mutateAsync(invoice.id)
              } catch (e) {
                setActionError(apiErrorMessage(e))
              }
            },
          },
      {
        label: 'Elimina',
        tone: 'danger',
        onSelect: () => {
          setActionError(null)
          setDeleting({ kind: 'invoice', item: invoice })
        },
      },
    ]
  }

  function paymentActions(payment: TaxPayment): RowMenuItem[] {
    return [
      { label: 'Modifica', onSelect: () => setPaying({ payment, draft: null }) },
      {
        label: 'Elimina',
        tone: 'danger',
        onSelect: () => {
          setActionError(null)
          setDeleting({ kind: 'payment', item: payment })
        },
      },
    ]
  }

  async function confirmDelete() {
    if (!deleting) return
    try {
      if (deleting.kind === 'invoice') await deleteInvoice.mutateAsync(deleting.item.id)
      else await deletePayment.mutateAsync(deleting.item.id)
      setDeleting(null)
    } catch (e) {
      setActionError(apiErrorMessage(e, 'Impossibile eliminare.'))
    }
  }

  const s = summary.data
  const revenue = toNumber(s?.figures.revenue)
  const limitShare = (revenue / REVENUE_LIMIT) * 100
  const liability = toNumber(s?.tax_liability)
  const gap = toNumber(s?.gap)

  const kpis: Kpi[] = s
    ? [
        {
          label: `Incassato ${year}`,
          value: <Money value={s.figures.revenue} />,
          sub: (
            <span className="flex flex-col gap-1">
              <ProgressBar value={limitShare} kind={limitShare >= 100 ? 'over' : limitShare >= 80 ? 'warn' : 'ok'} label={`${formatPercent(limitShare)} del limite di 85.000 €`} />
              {formatPercent(limitShare)} del limite di 85.000 €
            </span>
          ),
          subTone: limitShare >= 80 ? 'warn' : 'muted',
        },
        {
          label: 'Da accantonare',
          value: formatAmount(s.figures.to_provision, EUR),
          sub: `al ${pct(s.params.effective_provision_rate)}${s.params.provision_rate === null ? ' consigliato' : ''}`,
        },
        {
          label: liability < 0 ? 'Credito fiscale' : 'Debito fiscale',
          value: formatAmount(Math.abs(liability), EUR),
          sub: 'maturato sull’incassato, al netto dei versamenti',
        },
        {
          label: 'Da versare (F24)',
          value: formatAmount(s.cash_requirement, EUR),
          sub: 'acconti dell’anno prossimo inclusi',
        },
        {
          label: 'Accantonato',
          value: formatAmount(s.provision.total_base_currency, base),
          sub: s.provision.sources.length === 0 ? 'nessun conto scelto' : `${gap < 0 ? 'mancano' : 'margine'} ${formatAmount(Math.abs(gap), base)} ${base}`,
          subTone: s.provision.sources.length === 0 ? 'muted' : gap < 0 ? 'neg' : 'pos',
        },
      ]
    : []

  return (
    <>
      <PageHeader
        title="Fatture"
        subtitle="P.IVA forfettaria · le tasse maturano sull'incassato, alla data di incasso"
        actions={
          <>
            <YearPicker year={year} onChange={setYear} />
            <Button onClick={() => setPaying({ payment: null, draft: null })}>Registra F24</Button>
            <Button variant="primary" onClick={() => setEditing({ invoice: null })}>
              + Fattura
            </Button>
          </>
        }
      />

      {summary.isLoading ? (
        <LoadingBlock className="h-24" />
      ) : summary.isError ? (
        <ErrorBlock>Errore nel caricamento del riepilogo.</ErrorBlock>
      ) : (
        <KpiStrip label={`Riepilogo ${year}`} items={kpis} />
      )}

      {s && limitShare >= 80 && (
        <Notice>
          {limitShare >= 100
            ? 'Superato il limite di 85.000 € di ricavi: dal prossimo anno si esce dal forfettario (subito, oltre 100.000 €).'
            : 'Ti stai avvicinando al limite di 85.000 € di ricavi incassati.'}
        </Notice>
      )}

      {actionError && deleting === null && <ErrorBlock>{actionError}</ErrorBlock>}

      <Card
        title={`Fatture ${year}`}
        meta={
          s && toNumber(s.figures.outstanding) > 0 ? (
            <span className="text-[13px] font-bold text-ink-3 tabular-nums">da incassare {formatAmount(s.figures.outstanding, EUR)} €</span>
          ) : undefined
        }
        action={
          <SegmentedControl<Filter>
            label="Filtra fatture"
            size="sm"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: 'Tutte' },
              { value: 'collected', label: 'Incassate' },
              { value: 'outstanding', label: 'Da incassare' },
            ]}
          />
        }
      >
        {invoices.isLoading ? (
          <LoadingBlock className="mt-3 h-40" />
        ) : invoices.isError ? (
          <ErrorBlock>Errore nel caricamento delle fatture.</ErrorBlock>
        ) : list.length === 0 ? (
          <div className="mt-3">
            <EmptyState
              title={filter === 'all' ? `Nessuna fattura nel ${year}` : 'Nessuna fattura con questo filtro'}
              action={
                <Button variant="primary" onClick={() => setEditing({ invoice: null })}>
                  Aggiungi una fattura
                </Button>
              }
            >
              Qui compaiono le fatture emesse o incassate nell'anno. Per ognuna calcoliamo tasse, contributi, acconti e quanto mettere da parte.
            </EmptyState>
          </div>
        ) : (
          <div className="mt-2">
            <InvoicesTable invoices={list} year={year} actions={invoiceActions} />
          </div>
        )}
      </Card>

      {s && (
        <div className="grid gap-4 lg:grid-cols-2">
          <YearBreakdown summary={s} />
          <ProvisionCard summary={s} base={base} />
          <DeadlinesCard deadlines={s.deadlines} onPay={(draft) => setPaying({ payment: null, draft })} />
          <PaymentsCard payments={payments.data ?? []} accountName={accountName} actions={paymentActions} />
        </div>
      )}

      <InvoiceDialog open={editing !== null} invoice={editing?.invoice ?? null} onClose={() => setEditing(null)} />
      <CollectDialog invoice={collecting} onClose={() => setCollecting(null)} />
      <TaxPaymentDialog open={paying !== null} payment={paying?.payment ?? null} draft={paying?.draft ?? null} onClose={() => setPaying(null)} />
      <ConfirmDialog
        open={deleting !== null}
        title={deleting?.kind === 'invoice' ? `Eliminare la fattura a ${deleting.item.client}?` : 'Eliminare il versamento?'}
        confirmLabel="Elimina"
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
        pending={deleteInvoice.isPending || deletePayment.isPending}
        error={actionError}
      >
        {deleting?.kind === 'invoice'
          ? "Se l'entrata sul conto è stata creata da qui, sparisce anche quella. Un movimento importato e collegato resta."
          : "Sparisce anche l'eventuale uscita registrata sul conto."}
      </ConfirmDialog>
    </>
  )
}
