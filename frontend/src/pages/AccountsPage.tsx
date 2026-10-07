import { useState, type ComponentType, type SVGProps } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Delta } from '@/components/ui/Amount'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { CloseIcon, GridIcon, PlanIcon, TrendIcon, WalletIcon } from '@/components/ui/Icon'
import { KpiStrip, type Kpi } from '@/components/ui/KpiStrip'
import { PageHeader } from '@/components/ui/PageHeader'
import { RowMenu } from '@/components/ui/RowMenu'
import { useAccounts, useCreateAccount, useDeleteAccount, useUpdateAccount } from '@/hooks/useAccounts'
import { useAuth } from '@/hooks/useAuth'
import { useNetWorth } from '@/hooks/usePortfolio'
import { useSavingsGoals } from '@/hooks/useSavingsGoals'
import { useAllTransactions } from '@/hooks/useTransactions'
import { apiErrorMessage } from '@/lib/apiError'
import { CURRENCIES, CURRENCY_NAMES } from '@/lib/currencies'
import { monthRange } from '@/lib/dates'
import { formatAmount, formatFullDate, formatMonthName, formatPercent, toISODate, toNumber } from '@/lib/format'
import { ACCOUNT_TYPE_LABELS } from '@/lib/portfolio'
import { totals } from '@/lib/transactions'
import type { Account, AccountBalance, AccountType } from '@/types'

const TYPE_ORDER: AccountType[] = ['checking', 'cash', 'savings', 'credit_card', 'investment', 'crypto_wallet']

const GROUP_TITLES: Record<AccountType, string> = {
  checking: 'Conti correnti',
  savings: 'Risparmio e depositi',
  credit_card: 'Carte di credito',
  investment: 'Investimento',
  crypto_wallet: 'Wallet crypto',
  cash: 'Contanti',
}

function CardIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20" />
    </svg>
  )
}

function CashIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <circle cx="12" cy="12" r="2.5" />
      <path d="M6 12h.01M18 12h.01" />
    </svg>
  )
}

const TYPE_ICONS: Record<AccountType, ComponentType<SVGProps<SVGSVGElement>>> = {
  checking: WalletIcon,
  savings: PlanIcon,
  credit_card: CardIcon,
  investment: TrendIcon,
  crypto_wallet: GridIcon,
  cash: CashIcon,
}

const schema = z.object({
  name: z.string().trim().min(1, 'Il nome è obbligatorio').max(100, 'Massimo 100 caratteri'),
  type: z.enum(['checking', 'savings', 'credit_card', 'investment', 'crypto_wallet', 'cash']),
  currency: z.enum(CURRENCIES),
  starting_balance: z
    .string()
    .optional()
    .refine((v) => !v || Number.isFinite(Number(v.replace(/\./g, '').replace(',', '.'))), 'Inserisci un numero valido'),
})

type FormValues = z.infer<typeof schema>

/** "1.200,50" or "1200.50" → "1200.50" for the API. */
function parseLocaleNumber(value: string): string {
  const trimmed = value.trim()
  if (trimmed.includes(',')) return trimmed.replace(/\./g, '').replace(',', '.')
  return trimmed
}

function TypeTiles({ value, onChange, legend }: { value: AccountType; onChange: (type: AccountType) => void; legend: string }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-[14px] font-bold">{legend}</legend>
      <div role="radiogroup" className="grid grid-cols-2 gap-1.5">
        {TYPE_ORDER.map((type) => {
          const Icon = TYPE_ICONS[type]
          const on = type === value
          return (
            <button
              key={type}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => onChange(type)}
              className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-[10px] border px-3 text-left text-[14px] ${
                on ? 'border-accent bg-accent-soft font-extrabold text-accent' : 'border-field bg-card font-semibold text-ink-2 hover:bg-card-2'
              }`}
            >
              <Icon className="h-[18px] w-[18px] flex-none" />
              {ACCOUNT_TYPE_LABELS[type]}
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}

function NewAccountPanel({ balances, baseCurrency, onClose }: { balances: AccountBalance[]; baseCurrency: string; onClose: () => void }) {
  const createAccount = useCreateAccount()
  const [serverError, setServerError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    control,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', type: 'checking', currency: (CURRENCIES as readonly string[]).includes(baseCurrency) ? (baseCurrency as FormValues['currency']) : 'EUR', starting_balance: '' },
  })
  const type = useWatch({ control, name: 'type' })
  const currency = useWatch({ control, name: 'currency' })
  const startingBalance = useWatch({ control, name: 'starting_balance' })

  // Preview conversion with the rate already applied to another account in
  // the same currency (net worth values every account at today's rate).
  // There's no standalone rate endpoint, so without such an account the
  // preview is skipped rather than guessed.
  const sameCurrency = balances.find((b) => b.currency === currency && toNumber(b.balance) !== 0)
  const rate = currency === baseCurrency ? 1 : sameCurrency ? toNumber(sameCurrency.balance_base_currency) / toNumber(sameCurrency.balance) : null
  const amount = startingBalance ? Number(parseLocaleNumber(startingBalance)) : 0

  async function onSubmit(values: FormValues) {
    setServerError(null)
    try {
      await createAccount.mutateAsync({
        name: values.name.trim(),
        type: values.type,
        currency: values.currency,
        starting_balance: values.starting_balance ? parseLocaleNumber(values.starting_balance) : undefined,
      })
      onClose()
    } catch (error) {
      setServerError(apiErrorMessage(error, 'Impossibile creare il conto. Riprova.'))
    }
  }

  return (
    <section aria-labelledby="new-account" className="flex-[1_1_340px] self-start rounded-[14px] border border-line bg-card px-5 py-4 max-lg:order-first lg:sticky lg:top-20">
      <div className="flex items-center justify-between">
        <h2 id="new-account" className="text-[16px] font-extrabold">
          Nuovo conto
        </h2>
        <button type="button" onClick={onClose} aria-label="Chiudi" className="-mr-2 grid h-11 w-11 cursor-pointer place-items-center rounded-[10px] hover:bg-card-2">
          <CloseIcon className="h-5 w-5" />
        </button>
      </div>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-3 flex flex-col gap-4">
        <Field label="Nome" htmlFor="acc-name" error={errors.name?.message}>
          <input id="acc-name" className="field" aria-invalid={!!errors.name} aria-describedby={errors.name ? 'acc-name-msg' : undefined} {...register('name')} />
        </Field>
        <TypeTiles legend="Tipo" value={type} onChange={(next) => setValue('type', next)} />
        <div className="grid grid-cols-[120px_1fr] gap-2.5">
          <Field label="Valuta" htmlFor="acc-ccy">
            <select id="acc-ccy" className="field" {...register('currency')}>
              {CURRENCIES.map((c) => (
                <option key={c} value={c} title={CURRENCY_NAMES[c]}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Saldo iniziale" htmlFor="acc-start" error={errors.starting_balance?.message}>
            <div className="relative">
              <input
                id="acc-start"
                inputMode="decimal"
                placeholder="0,00"
                aria-invalid={!!errors.starting_balance}
                aria-describedby="acc-start-help"
                className="field pr-12 tabular-nums"
                {...register('starting_balance')}
              />
              <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">{currency}</span>
            </div>
          </Field>
        </div>
        <p id="acc-start-help" className="-mt-2 text-[12px] text-ink-3 tabular-nums">
          {amount && rate !== null && currency !== baseCurrency
            ? `≈ ${formatAmount(amount * rate, baseCurrency)} ${baseCurrency} al cambio di oggi. `
            : ''}
          Diventa il movimento di apertura del conto.
        </p>
        <p role="note" className="rounded-[10px] bg-warn-soft px-3 py-2 text-[13px] font-bold text-warn">
          La valuta non si può cambiare dopo la creazione. Nome e tipo sì.
        </p>
        {serverError && <ErrorBlock>{serverError}</ErrorBlock>}
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? 'Creazione…' : 'Crea conto'}
        </Button>
      </form>
    </section>
  )
}

function EditAccountDialog({ account, onClose }: { account: Account | null; onClose: () => void }) {
  return (
    <Dialog open={!!account} onClose={onClose} title="Modifica conto" description="La valuta resta quella scelta alla creazione.">
      {account && <EditAccountForm key={account.id} account={account} onClose={onClose} />}
    </Dialog>
  )
}

function EditAccountForm({ account, onClose }: { account: Account; onClose: () => void }) {
  const updateAccount = useUpdateAccount()
  const [name, setName] = useState(account.name)
  const [type, setType] = useState<AccountType>(account.type)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    if (!name.trim()) {
      setError('Il nome è obbligatorio')
      return
    }
    try {
      await updateAccount.mutateAsync({ id: account.id, payload: { name: name.trim(), type } })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Field label="Nome" htmlFor="edit-acc-name">
        <input id="edit-acc-name" className="field" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <TypeTiles legend="Tipo" value={type} onChange={setType} />
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={save} disabled={updateAccount.isPending}>
          Salva
        </Button>
      </div>
    </div>
  )
}

function CloseAccountDialog({ account, balance, goal, onClose }: { account: Account | null; balance: AccountBalance | undefined; goal: string | undefined; onClose: () => void }) {
  return (
    <Dialog open={!!account} onClose={onClose} title={`Chiudere “${account?.name}”?`} description="Resta nello storico con i suoi movimenti; dopo la data di chiusura non ne accetta di nuovi.">
      {account && <CloseAccountForm key={account.id} account={account} balance={balance} goal={goal} onClose={onClose} />}
    </Dialog>
  )
}

function CloseAccountForm({ account, balance, goal, onClose }: { account: Account; balance: AccountBalance | undefined; goal: string | undefined; onClose: () => void }) {
  const updateAccount = useUpdateAccount()
  const [today] = useState(() => toISODate(new Date()))
  const [closedAt, setClosedAt] = useState(today)
  const [error, setError] = useState<string | null>(null)
  const leftover = balance ? toNumber(balance.balance) : 0

  async function save() {
    if (!closedAt) {
      setError('Indica la data di chiusura')
      return
    }
    if (closedAt > today) {
      setError('La data di chiusura non può essere nel futuro')
      return
    }
    setError(null)
    try {
      await updateAccount.mutateAsync({ id: account.id, payload: { closed_at: closedAt } })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile chiudere il conto.'))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Field label="Data di chiusura" htmlFor="close-date">
        <input id="close-date" type="date" className="field" max={today} value={closedAt} onChange={(e) => setClosedAt(e.target.value)} />
      </Field>
      {leftover !== 0 && (
        <p role="note" className="rounded-[10px] bg-warn-soft px-3 py-2 text-[13px] font-bold text-warn tabular-nums">
          Il saldo è {formatAmount(leftover, account.currency)} {account.currency}: resta nel patrimonio anche a conto chiuso. Se il denaro è stato spostato altrove, registra prima il giroconto.
        </p>
      )}
      {goal && <p className="text-[13px] font-bold text-warn">Finanzia l'obiettivo “{goal}”: scollegalo dal piano prima di chiuderlo.</p>}
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={save} disabled={updateAccount.isPending}>
          {updateAccount.isPending ? 'Attendi…' : 'Chiudi conto'}
        </Button>
      </div>
    </div>
  )
}

export function AccountsPage() {
  const { user } = useAuth()
  const base = user?.base_currency ?? ''
  const [today] = useState(() => new Date())
  const { data: accounts, isLoading, isError } = useAccounts()
  const netWorth = useNetWorth()
  const { data: goals } = useSavingsGoals()
  const month = useAllTransactions(monthRange(today))
  const deleteAccount = useDeleteAccount()
  const reopenAccount = useUpdateAccount()
  const [formOpen, setFormOpen] = useState(false)
  const [closing, setClosing] = useState<Account | null>(null)
  const [reopenError, setReopenError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Account | null>(null)
  const [deleting, setDeleting] = useState<Account | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const balances = netWorth.data?.accounts ?? []
  const balanceById = new Map(balances.map((b) => [b.account_id, b]))
  const goalByAccount = new Map<string, string>()
  for (const goal of goals ?? []) {
    if (goal.deleted_at) continue
    for (const source of goal.sources) goalByAccount.set(source.account_id, goal.name)
  }

  const openAccounts = (accounts ?? []).filter((a) => !a.closed_at)
  // Most recently closed first: the one you just closed is the one you look for.
  const closedAccounts = (accounts ?? []).filter((a) => a.closed_at).sort((a, b) => (b.closed_at ?? '').localeCompare(a.closed_at ?? ''))
  const closedIds = new Set(closedAccounts.map((a) => a.id))

  const total = toNumber(netWorth.data?.total_cash_balance)
  const byCurrency = new Map<string, { native: number; base: number; count: number }>()
  for (const b of balances) {
    // An emptied closed account adds nothing but a misleading "N conti".
    if (closedIds.has(b.account_id) && toNumber(b.balance) === 0) continue
    const entry = byCurrency.get(b.currency) ?? { native: 0, base: 0, count: 0 }
    entry.native += toNumber(b.balance)
    entry.base += toNumber(b.balance_base_currency)
    entry.count += 1
    byCurrency.set(b.currency, entry)
  }
  const monthTotals = totals(month.data ?? [])

  const kpis: Kpi[] = [
    {
      label: 'Liquidità totale',
      value: (
        <>
          {formatAmount(total, base)} <span className="ccy">{base}</span>
        </>
      ),
      sub: `${openAccounts.length} conti attivi`,
    },
    ...[...byCurrency.entries()]
      .sort((a, b) => b[1].base - a[1].base)
      .map(([currency, entry]) => ({
        label: `In ${currency}`,
        value: (
          <>
            {formatAmount(entry.native, currency)} <span className="ccy">{currency}</span>
          </>
        ),
        sub:
          (currency !== base ? `≈ ${formatAmount(entry.base, base)} ${base} · ` : '') +
          `${formatPercent(total ? (entry.base / total) * 100 : 0)} · ${entry.count} ${entry.count === 1 ? 'conto' : 'conti'}`,
      })),
    {
      label: `Variazione in ${formatMonthName(today)}`,
      value: <Delta value={monthTotals.net} currency={base} className="font-extrabold" />,
      sub: 'entrate − uscite, giroconti esclusi',
    },
  ]

  async function confirmDelete() {
    if (!deleting) return
    setDeleteError(null)
    try {
      await deleteAccount.mutateAsync(deleting.id)
      setDeleting(null)
    } catch (error) {
      setDeleteError(apiErrorMessage(error, 'Impossibile eliminare il conto.'))
    }
  }

  async function reopen(account: Account) {
    setReopenError(null)
    try {
      await reopenAccount.mutateAsync({ id: account.id, payload: { closed_at: null } })
    } catch (error) {
      setReopenError(apiErrorMessage(error, 'Impossibile riaprire il conto.'))
    }
  }

  function askDelete(account: Account) {
    setDeleteError(null)
    setDeleting(account)
  }

  const groups = TYPE_ORDER.map((type) => ({ type, items: openAccounts.filter((a) => a.type === type) })).filter((g) => g.items.length)

  return (
    <>
      <PageHeader
        title="Conti"
        subtitle={`Saldi al ${formatFullDate(today)} · ogni conto nella sua valuta, totali in ${base}`}
        actions={
          <Button variant="primary" aria-expanded={formOpen} onClick={() => setFormOpen((o) => !o)}>
            + Nuovo conto
          </Button>
        }
      />

      <KpiStrip label="Riepilogo liquidità" items={kpis} />

      <div className="flex flex-wrap items-start gap-4">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-4">
          {isLoading ? (
            <LoadingBlock className="h-64" />
          ) : isError ? (
            <ErrorBlock>Errore nel caricamento dei conti.</ErrorBlock>
          ) : groups.length === 0 && closedAccounts.length === 0 ? (
            <Card>
              <EmptyState title="Ancora nessun conto" action={<Button variant="primary" onClick={() => setFormOpen(true)}>Crea il primo conto</Button>}>
                Aggiungi un conto corrente, un deposito o un conto titoli per iniziare.
              </EmptyState>
            </Card>
          ) : (
            groups.map(({ type, items }) => {
              const Icon = TYPE_ICONS[type]
              const groupTotal = items.reduce((s, a) => s + toNumber(balanceById.get(a.id)?.balance_base_currency), 0)
              return (
                <section key={type} aria-label={GROUP_TITLES[type]} className="rounded-[14px] border border-line bg-card px-4 pt-1.5 pb-2 sm:px-5">
                  <div className="flex items-baseline justify-between pt-2.5 pb-1.5 tabular-nums">
                    <h2 className="text-[13px] font-extrabold text-ink-2">{GROUP_TITLES[type]}</h2>
                    <span className="text-[12px] font-bold text-ink-3">
                      {formatAmount(groupTotal, base)} {base}
                    </span>
                  </div>
                  <ul>
                    {items.map((account) => {
                      const balance = balanceById.get(account.id)
                      const goal = goalByAccount.get(account.id)
                      return (
                        <li key={account.id} className="flex items-center gap-3 border-t border-line py-3 tabular-nums">
                          <span className="grid h-10 w-10 flex-none place-items-center rounded-[10px] bg-card-2 text-ink-2 max-sm:hidden">
                            <Icon className="h-5 w-5" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px] font-extrabold">
                              <span className="min-w-0 break-words">{account.name}</span>
                              <span className="rounded bg-card-2 px-1.5 text-[11px] font-bold text-ink-3">{account.currency}</span>
                              {goal && <span className="rounded-full bg-accent-soft px-2 text-[11px] font-bold text-accent">Obiettivo: {goal}</span>}
                            </div>
                            <div className="text-[12px] text-ink-3">
                              {ACCOUNT_TYPE_LABELS[account.type]}
                              <span className="max-sm:hidden"> · aperto il {formatFullDate(account.created_at.slice(0, 10))}</span>
                            </div>
                          </div>
                          <div className="flex-none text-right">
                            <div className="text-[16px] font-extrabold whitespace-nowrap">
                              {balance ? formatAmount(balance.balance, account.currency) : '…'} <span className="ccy">{account.currency}</span>
                            </div>
                            {balance && account.currency !== base && (
                              <div className="text-[12px] whitespace-nowrap text-ink-3">
                                ≈ {formatAmount(balance.balance_base_currency, base)} {base}
                              </div>
                            )}
                          </div>
                          <RowMenu
                            label={`Azioni per ${account.name}`}
                            items={[
                              { label: 'Modifica nome e tipo', onSelect: () => setEditing(account) },
                              { label: 'Chiudi conto', onSelect: () => setClosing(account) },
                              { label: 'Elimina', tone: 'danger', onSelect: () => askDelete(account) },
                            ]}
                          />
                        </li>
                      )
                    })}
                  </ul>
                </section>
              )
            })
          )}

          {closedAccounts.length > 0 && (
            <details className="group rounded-[14px] border border-line bg-card px-4 sm:px-5">
              <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between py-2.5 text-[13px] font-extrabold text-ink-2">
                <span>Conti chiusi · {closedAccounts.length}</span>
                <span aria-hidden="true" className="text-ink-3 transition-transform group-open:rotate-90">
                  ›
                </span>
              </summary>
              {reopenError && <ErrorBlock>{reopenError}</ErrorBlock>}
              <ul className="pb-2">
                {closedAccounts.map((account) => {
                  const balance = balanceById.get(account.id)
                  const leftover = balance ? toNumber(balance.balance) : 0
                  return (
                    <li key={account.id} className="flex items-center gap-3 border-t border-line py-3 tabular-nums">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px] font-bold text-ink-2">
                          <span className="min-w-0 break-words">{account.name}</span>
                          <span className="rounded bg-card-2 px-1.5 text-[11px] font-bold text-ink-3">{account.currency}</span>
                        </div>
                        <div className="text-[12px] text-ink-3">
                          {ACCOUNT_TYPE_LABELS[account.type]} · chiuso il {formatFullDate(account.closed_at!)}
                        </div>
                      </div>
                      <div className={`flex-none text-right text-[14px] font-bold whitespace-nowrap ${leftover !== 0 ? 'text-warn' : 'text-ink-3'}`}>
                        {balance ? formatAmount(balance.balance, account.currency) : '…'} <span className="ccy">{account.currency}</span>
                      </div>
                      <RowMenu
                        label={`Azioni per ${account.name}`}
                        items={[
                          { label: 'Riapri', onSelect: () => reopen(account) },
                          { label: 'Modifica nome e tipo', onSelect: () => setEditing(account) },
                          { label: 'Elimina', tone: 'danger', onSelect: () => askDelete(account) },
                        ]}
                      />
                    </li>
                  )
                })}
              </ul>
            </details>
          )}
        </div>

        {formOpen && <NewAccountPanel balances={balances} baseCurrency={base} onClose={() => setFormOpen(false)} />}
      </div>

      <EditAccountDialog account={editing} onClose={() => setEditing(null)} />
      <CloseAccountDialog
        account={closing}
        balance={closing ? balanceById.get(closing.id) : undefined}
        goal={closing ? goalByAccount.get(closing.id) : undefined}
        onClose={() => setClosing(null)}
      />
      <ConfirmDialog
        open={!!deleting}
        title={`Eliminare “${deleting?.name}”?`}
        confirmLabel="Elimina conto"
        pending={deleteAccount.isPending}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      >
        Il conto sparisce da saldi e patrimonio; i suoi movimenti restano nello storico e nei report.
        {deleting && goalByAccount.has(deleting.id) && (
          <p className="mt-2 font-bold text-warn">
            Finanzia l'obiettivo “{goalByAccount.get(deleting.id)}”: scollegalo dal piano prima di eliminarlo.
          </p>
        )}
      </ConfirmDialog>
    </>
  )
}
