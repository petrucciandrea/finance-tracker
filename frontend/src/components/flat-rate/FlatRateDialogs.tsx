import { useState } from 'react'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import {
  useCollectInvoice,
  useCollectionCandidates,
  useCreateInvoice,
  useCreateTaxPayment,
  useFlatRateYear,
  useInvoiceClients,
  useUpdateInvoice,
  useUpdateTaxPayment,
} from '@/hooks/useFlatRate'
import { apiErrorMessage } from '@/lib/apiError'
import {
  autoStampDuty,
  isPercentInput,
  percentInputToRate,
  previewInvoice,
  rateToPercentInput,
  TAX_COMPONENT_LABELS,
  TAX_KIND_LABELS,
} from '@/lib/flatRate'
import { formatAmount, formatFullDate, formatPercent, toISODate, toNumber } from '@/lib/format'
import { isLocaleNumber, parseLocaleNumber } from '@/lib/physicalAssets'
import type { Account, Invoice, TaxComponent, TaxPayment, TaxPaymentKind } from '@/types'

const EUR = 'EUR'

function eurAccounts(accounts: Account[] | undefined): Account[] {
  // The backend refuses other currencies (no conversion inside a multi-row
  // write) and closed accounts take no new movements.
  return (accounts ?? []).filter((a) => a.currency === EUR && !a.closed_at)
}

function MoneyInput({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative">
      <input id={id} inputMode="decimal" placeholder="0,00" className="field pr-12 tabular-nums" value={value} onChange={(e) => onChange(e.target.value)} />
      <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">{EUR}</span>
    </div>
  )
}

function PreviewRow({ label, value, strong = false }: { label: string; value: number; strong?: boolean }) {
  return (
    <div className={`flex justify-between gap-3 ${strong ? 'font-extrabold text-ink' : ''}`}>
      <span>{label}</span>
      <span className="tabular-nums">
        {formatAmount(value, EUR)} <span className="ccy">{EUR}</span>
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Invoice create / edit
// ---------------------------------------------------------------------------

export function InvoiceDialog({ open, invoice, onClose }: { open: boolean; invoice: Invoice | null; onClose: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="md"
      title={invoice ? `Modifica fattura${invoice.number ? ` ${invoice.number}` : ''}` : 'Nuova fattura'}
      description="Le tasse maturano alla data di incasso: segna la fattura come incassata quando arriva il pagamento."
    >
      {open && <InvoiceForm key={invoice?.id ?? 'new'} invoice={invoice} onClose={onClose} />}
    </Dialog>
  )
}

function InvoiceForm({ invoice, onClose }: { invoice: Invoice | null; onClose: () => void }) {
  const create = useCreateInvoice()
  const update = useUpdateInvoice()
  const [number, setNumber] = useState(invoice?.number ?? '')
  const [client, setClient] = useState(invoice?.client ?? '')
  const [issueDate, setIssueDate] = useState(invoice?.issue_date ?? toISODate(new Date()))
  const [collectedOn, setCollectedOn] = useState(invoice?.collected_on ?? '')
  const { data: clients } = useInvoiceClients()
  const [amount, setAmount] = useState(invoice ? invoice.amount.replace('.', ',') : '')
  const [rivalsa, setRivalsa] = useState<boolean | null>(invoice ? toNumber(invoice.rivalsa_rate) > 0 : null)
  // null = follow the €77,47 rule; a click makes it an explicit choice.
  const [stampDuty, setStampDuty] = useState<boolean | null>(invoice ? invoice.stamp_duty : null)
  const [provision, setProvision] = useState(rateToPercentInput(invoice?.provision_rate))
  const [notes, setNotes] = useState(invoice?.notes ?? '')
  const [error, setError] = useState<string | null>(null)

  // The fiscal year an invoice is taxed in is its collection year; until
  // then the issue year's parameters are the best guess.
  const fiscalYear = Number((collectedOn || issueDate).slice(0, 4)) || new Date().getFullYear()
  const { data: year } = useFlatRateYear(fiscalYear)

  const yearRivalsa = toNumber(year?.rivalsa_rate)
  const rivalsaOn = rivalsa ?? yearRivalsa > 0
  // A frozen rate is kept on edit; turning it on uses the year's (or 4%).
  const rivalsaRate = !rivalsaOn ? 0 : invoice && toNumber(invoice.rivalsa_rate) > 0 ? toNumber(invoice.rivalsa_rate) : yearRivalsa || 0.04
  const amountValue = isLocaleNumber(amount) ? Number(parseLocaleNumber(amount)) : 0
  const stampOn = stampDuty ?? autoStampDuty(amountValue, rivalsaRate)
  const provisionValid = provision.trim() === '' || isPercentInput(provision)
  const provisionRate = provision.trim() !== '' && provisionValid ? Number(percentInputToRate(provision)) : toNumber(year?.effective_provision_rate)

  const preview = year
    ? previewInvoice({
        amount: amountValue,
        rivalsaRate,
        stampDuty: stampOn,
        coefficient: toNumber(year.profitability_coefficient),
        taxRate: toNumber(year.substitute_tax_rate),
        inpsRate: toNumber(year.inps_rate),
        provisionRate,
      })
    : null

  async function submit() {
    if (!client.trim()) return setError('Inserisci il cliente')
    if (!isLocaleNumber(amount) || amountValue <= 0) return setError('Inserisci un importo valido')
    if (!provisionValid) return setError('La percentuale di accantonamento va da 0 a 100')
    if (invoice?.collected_on && !collectedOn) return setError("Inserisci la data di incasso, o annulla l'incasso dal menu della fattura")
    setError(null)
    const payload = {
      number: number.trim() || null,
      client: client.trim(),
      issue_date: issueDate,
      amount: parseLocaleNumber(amount),
      rivalsa_rate: rivalsaRate.toFixed(4),
      stamp_duty: stampOn,
      provision_rate: provision.trim() === '' ? null : percentInputToRate(provision),
      notes: notes.trim() || null,
    }
    try {
      if (invoice)
        await update.mutateAsync({
          id: invoice.id,
          payload: invoice.collected_on && collectedOn !== invoice.collected_on ? { ...payload, collected_on: collectedOn } : payload,
        })
      else await create.mutateAsync(payload)
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare la fattura.'))
    }
  }

  const pending = create.isPending || update.isPending
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-2.5 sm:grid-cols-[1fr_2fr]">
        <Field label="Numero" htmlFor="inv-number" hint="Facoltativo.">
          <input id="inv-number" className="field" placeholder="Es. 12/2026" value={number} onChange={(e) => setNumber(e.target.value)} />
        </Field>
        <Field label="Cliente" htmlFor="inv-client">
          {/* Native suggestions: the browser lists the matches under the
              field as you type, and any new name is still accepted. */}
          <input id="inv-client" className="field" list="inv-client-options" autoComplete="off" value={client} onChange={(e) => setClient(e.target.value)} />
          <datalist id="inv-client-options">
            {(clients ?? []).map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Data fattura" htmlFor="inv-date">
          <input id="inv-date" type="date" className="field" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
        </Field>
        <Field label="Compenso" htmlFor="inv-amount">
          <MoneyInput id="inv-amount" value={amount} onChange={setAmount} />
        </Field>
      </div>
      {invoice?.collected_on && (
        <Field
          label="Data di incasso"
          htmlFor="inv-collected"
          hint={
            invoice.owns_transaction
              ? "Sposta anche l'entrata registrata sul conto. Decide l'anno in cui la fattura è tassata."
              : invoice.transaction_id
                ? "Il movimento collegato resta alla sua data. Decide l'anno in cui la fattura è tassata."
                : "Decide l'anno in cui la fattura è tassata."
          }
        >
          <input id="inv-collected" type="date" className="field" value={collectedOn} onChange={(e) => setCollectedOn(e.target.value)} />
        </Field>
      )}
      <div className="flex flex-col gap-2">
        <label className="flex min-h-11 w-fit cursor-pointer items-center gap-2 text-[14px] font-semibold">
          <input type="checkbox" className="h-4 w-4" checked={rivalsaOn} onChange={(e) => setRivalsa(e.target.checked)} />
          Rivalsa INPS {formatPercent(rivalsaOn ? rivalsaRate * 100 : (yearRivalsa || 0.04) * 100)} a carico del cliente
        </label>
        <label className="flex min-h-11 w-fit cursor-pointer items-center gap-2 text-[14px] font-semibold">
          <input type="checkbox" className="h-4 w-4" checked={stampOn} onChange={(e) => setStampDuty(e.target.checked)} />
          Bollo da 2 € addebitato al cliente
          {stampDuty === null && <span className="font-normal text-ink-3">(automatico sopra 77,47 €)</span>}
        </label>
      </div>
      <Field
        label="Accantonamento"
        htmlFor="inv-provision"
        hint={
          year
            ? `Vuoto = quello dell'anno, ${formatPercent(toNumber(year.effective_provision_rate) * 100, { digits: 0 })}${
                year.provision_rate === null ? ' consigliato' : ''
              }.`
            : undefined
        }
      >
        <div className="relative">
          <input
            id="inv-provision"
            inputMode="decimal"
            className="field pr-10 tabular-nums"
            placeholder={year ? rateToPercentInput(year.effective_provision_rate) : ''}
            value={provision}
            onChange={(e) => setProvision(e.target.value)}
          />
          <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">%</span>
        </div>
      </Field>
      <Field label="Note" htmlFor="inv-notes">
        <input id="inv-notes" className="field" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>

      {preview && amountValue > 0 && (
        <div className="rounded-[12px] bg-card-2 px-3 py-2.5 text-[13px] text-ink-2">
          {preview.rivalsa > 0 && <PreviewRow label="Rivalsa INPS" value={preview.rivalsa} />}
          {preview.stamp > 0 && <PreviewRow label="Bollo" value={preview.stamp} />}
          <PreviewRow label="Totale fattura" value={preview.total} strong />
          <PreviewRow label={`Imponibile (${formatPercent(toNumber(year?.profitability_coefficient) * 100, { digits: 0 })})`} value={preview.taxableBase} />
          <PreviewRow label="Imposta sostitutiva" value={preview.substituteTax} />
          <PreviewRow label="INPS" value={preview.inps} />
          <PreviewRow label={`Da accantonare (${formatPercent(provisionRate * 100, { digits: 0 })})`} value={preview.toProvision} strong />
        </div>
      )}

      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={submit} disabled={pending}>
          {pending ? 'Attendi…' : invoice ? 'Salva' : 'Aggiungi fattura'}
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Collect
// ---------------------------------------------------------------------------

type CollectMode = 'link' | 'create' | 'none'

export function CollectDialog({ invoice, onClose }: { invoice: Invoice | null; onClose: () => void }) {
  return (
    <Dialog
      open={!!invoice}
      onClose={onClose}
      size="md"
      title={invoice ? `Incasso · ${invoice.client}` : ''}
      description={
        invoice
          ? `Totale ${formatAmount(invoice.total, EUR)} ${EUR}. Le tasse di questa fattura cadono nell'anno della data di incasso.`
          : undefined
      }
    >
      {invoice && <CollectForm key={invoice.id} invoice={invoice} onClose={onClose} />}
    </Dialog>
  )
}

function CollectForm({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const collect = useCollectInvoice()
  const { data: candidates, isLoading } = useCollectionCandidates(invoice.id)
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const [mode, setMode] = useState<CollectMode>('link')
  const [collectedOn, setCollectedOn] = useState(() => toISODate(new Date()))
  const [transactionId, setTransactionId] = useState('')
  const [accountId, setAccountId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const accountsById = new Map((accounts ?? []).map((a) => [a.id, a]))
  const receiving = eurAccounts(accounts)

  async function submit() {
    if (mode === 'link' && !transactionId) return setError('Scegli il movimento che ha incassato la fattura')
    if (mode === 'create' && !accountId) return setError('Scegli il conto su cui è arrivato il pagamento')
    setError(null)
    try {
      await collect.mutateAsync({
        id: invoice.id,
        payload: {
          collected_on: collectedOn,
          transaction_id: mode === 'link' ? transactionId : null,
          account_id: mode === 'create' ? accountId : null,
          category_id: mode === 'create' && categoryId ? categoryId : null,
        },
      })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, "Impossibile registrare l'incasso."))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl<CollectMode>
        label="Movimento sul conto"
        value={mode}
        onChange={setMode}
        options={[
          { value: 'link', label: 'Collega un movimento' },
          { value: 'create', label: 'Crea un’entrata' },
          { value: 'none', label: 'Solo la data' },
        ]}
      />

      {mode === 'link' &&
        (isLoading ? (
          <LoadingBlock className="h-20" />
        ) : (candidates ?? []).length === 0 ? (
          <p className="rounded-[10px] bg-card-2 px-3 py-2.5 text-[13px] text-ink-2">
            Nessuna entrata da {formatAmount(invoice.total, EUR)} {EUR} vicina alla data della fattura. Importala dall&apos;estratto conto, oppure crea
            l&apos;entrata da qui.
          </p>
        ) : (
          <fieldset className="flex flex-col gap-1">
            <legend className="mb-1.5 text-[14px] font-bold">Entrata corrispondente</legend>
            {candidates!.map((t) => (
              <label key={t.id} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-[10px] border border-line px-3 py-2 hover:bg-card-2">
                <input
                  type="radio"
                  name="candidate"
                  className="h-4 w-4"
                  checked={transactionId === t.id}
                  onChange={() => {
                    setTransactionId(t.id)
                    setCollectedOn(t.date)
                  }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-bold">{t.description || 'Entrata'}</span>
                  <span className="text-[12px] text-ink-3">
                    {formatFullDate(t.date)} · {accountsById.get(t.account_id)?.name ?? 'Conto'}
                  </span>
                </span>
                <span className="font-bold tabular-nums">
                  {formatAmount(t.amount, t.currency)} <span className="ccy">{t.currency}</span>
                </span>
              </label>
            ))}
          </fieldset>
        ))}

      {mode === 'create' && (
        <>
          <Field label="Incassato su" htmlFor="collect-account" hint="Solo conti in EUR aperti.">
            <select id="collect-account" className="field" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">Scegli un conto</option>
              {receiving.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Categoria" htmlFor="collect-category" hint="Vuota = «Varie», come ogni entrata senza categoria.">
            <CategorySelect id="collect-category" categories={categories} type="income" emptyLabel="Varie" value={categoryId} onChange={(e) => setCategoryId(e.target.value)} />
          </Field>
        </>
      )}

      {mode === 'none' && (
        <p className="text-[13px] text-ink-2">Registra solo la data: l&apos;entrata sul conto la gestisci tu, ad esempio con l&apos;import CSV.</p>
      )}

      <Field label="Data di incasso" htmlFor="collect-date">
        <input id="collect-date" type="date" className="field" value={collectedOn} onChange={(e) => setCollectedOn(e.target.value)} />
      </Field>

      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={submit} disabled={collect.isPending}>
          {collect.isPending ? 'Attendi…' : 'Segna come incassata'}
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// F24 payment create / edit
// ---------------------------------------------------------------------------

export interface PaymentDraft {
  fiscal_year: number
  component: TaxComponent
  kind: TaxPaymentKind
  amount: string
  paid_on?: string
}

export function TaxPaymentDialog({
  open,
  payment,
  draft,
  onClose,
}: {
  open: boolean
  payment: TaxPayment | null
  draft: PaymentDraft | null
  onClose: () => void
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="md"
      title={payment ? 'Modifica versamento F24' : 'Registra versamento F24'}
      description="Una riga dell'F24: saldo o acconto, imposta o INPS. Pagarlo da un conto non è una spesa: riduce la liquidità e il debito fiscale insieme."
    >
      {open && <TaxPaymentForm key={payment?.id ?? 'new'} payment={payment} draft={draft} onClose={onClose} />}
    </Dialog>
  )
}

function TaxPaymentForm({ payment, draft, onClose }: { payment: TaxPayment | null; draft: PaymentDraft | null; onClose: () => void }) {
  const create = useCreateTaxPayment()
  const update = useUpdateTaxPayment()
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const thisYear = new Date().getFullYear()
  const [paidOn, setPaidOn] = useState(payment?.paid_on ?? draft?.paid_on ?? toISODate(new Date()))
  const [fiscalYear, setFiscalYear] = useState(String(payment?.fiscal_year ?? draft?.fiscal_year ?? thisYear - 1))
  const [component, setComponent] = useState<TaxComponent>(payment?.component ?? draft?.component ?? 'substitute_tax')
  const [kind, setKind] = useState<TaxPaymentKind>(payment?.kind ?? draft?.kind ?? 'balance')
  const [amount, setAmount] = useState(
    payment ? payment.amount.replace('.', ',') : draft ? Number(draft.amount).toFixed(2).replace('.', ',') : '',
  )
  const [accountId, setAccountId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [notes, setNotes] = useState(payment?.notes ?? '')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!isLocaleNumber(amount) || Number(parseLocaleNumber(amount)) <= 0) return setError('Inserisci un importo valido')
    const year = Number(fiscalYear)
    if (!Number.isInteger(year) || year < 2000 || year > 2100) return setError("Inserisci l'anno di competenza")
    setError(null)
    const common = { paid_on: paidOn, fiscal_year: year, component, kind, amount: parseLocaleNumber(amount), notes: notes.trim() || null }
    try {
      if (payment) await update.mutateAsync({ id: payment.id, payload: common })
      else await create.mutateAsync({ ...common, account_id: accountId || null, category_id: accountId && categoryId ? categoryId : null })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare il versamento.'))
    }
  }

  const pending = create.isPending || update.isPending
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Tributo" htmlFor="pay-component">
          <select id="pay-component" className="field" value={component} onChange={(e) => setComponent(e.target.value as TaxComponent)}>
            {Object.entries(TAX_COMPONENT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Tipo" htmlFor="pay-kind">
          <select id="pay-kind" className="field" value={kind} onChange={(e) => setKind(e.target.value as TaxPaymentKind)}>
            {Object.entries(TAX_KIND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Anno di competenza" htmlFor="pay-year" hint="Il saldo 2026 si versa nel 2027.">
          <input id="pay-year" inputMode="numeric" className="field tabular-nums" value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value)} />
        </Field>
        <Field label="Data di pagamento" htmlFor="pay-date">
          <input id="pay-date" type="date" className="field" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </Field>
      </div>
      <Field label="Importo" htmlFor="pay-amount">
        <MoneyInput id="pay-amount" value={amount} onChange={setAmount} />
      </Field>
      {!payment && (
        <>
          <Field label="Pagato da" htmlFor="pay-account" hint="Facoltativo: registra l'uscita come giroconto sul conto scelto.">
            <select id="pay-account" className="field" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">Nessun conto</option>
              {eurAccounts(accounts).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
          {accountId && (
            <Field label="Categoria del giroconto" htmlFor="pay-category">
              <CategorySelect id="pay-category" categories={categories} type="transfer" emptyLabel="Nessuna categoria" value={categoryId} onChange={(e) => setCategoryId(e.target.value)} />
            </Field>
          )}
        </>
      )}
      <Field label="Note" htmlFor="pay-notes">
        <input id="pay-notes" className="field" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={submit} disabled={pending}>
          {pending ? 'Attendi…' : payment ? 'Salva' : 'Registra'}
        </Button>
      </div>
    </div>
  )
}
