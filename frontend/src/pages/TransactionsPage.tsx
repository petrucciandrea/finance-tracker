import { useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { TransactionFormDialog } from '@/components/transactions/TransactionFormDialog'
import { TransactionImport } from '@/components/transactions/TransactionImport'
import { Amount } from '@/components/ui/Amount'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import { SearchIcon, UploadIcon } from '@/components/ui/Icon'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pagination } from '@/components/ui/Pagination'
import { RowMenu } from '@/components/ui/RowMenu'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAccounts } from '@/hooks/useAccounts'
import { useAuth } from '@/hooks/useAuth'
import { useCategories } from '@/hooks/useCategories'
import { useAllTransactions, useDeleteTransaction, useTransactionsList } from '@/hooks/useTransactions'
import { apiErrorMessage } from '@/lib/apiError'
import { categoryPath, indexById, isMiscCategory, NECESSITY_LABELS, transactionNecessity } from '@/lib/categories'
import { formatAmount, formatDayHeader } from '@/lib/format'
import { accountLabel, amountKind, totals } from '@/lib/transactions'
import {
  PAGE_SIZES,
  PERIOD_LABELS,
  periodPhrase,
  periodRange,
  readFilters,
  type PeriodKey,
  type TransactionFilters,
} from '@/lib/transactionFilters'
import type { Account, Category, Transaction, TransactionType } from '@/types'

const TYPE_OPTIONS: { value: TransactionType | ''; label: string }[] = [
  { value: '', label: 'Tutti' },
  { value: 'expense', label: 'Uscite' },
  { value: 'income', label: 'Entrate' },
  { value: 'transfer', label: 'Trasferimenti' },
]

const TYPE_LABELS: Record<TransactionType, string> = { expense: 'Uscite', income: 'Entrate', transfer: 'Trasferimenti' }

interface Lookups {
  categories: Map<string, Category>
  accounts: Map<string, Account>
  baseCurrency: string
}

function CategoryCell({ t, lookups, onAssign }: { t: Transaction; lookups: Lookups; onAssign: () => void }) {
  if (t.type === 'transfer') {
    return <span className="rounded-full bg-card-2 px-2 py-0.5 text-[12px] font-bold text-ink-3">⇄ Trasferimento</span>
  }
  const category = lookups.categories.get(t.category_id ?? '')
  if (!category || isMiscCategory(category)) {
    return (
      <button
        type="button"
        onClick={onAssign}
        className="min-h-8 cursor-pointer rounded-full bg-warn-soft px-2.5 text-[12px] font-bold whitespace-nowrap text-warn hover:underline"
      >
        {category ? 'Varie' : 'Senza categoria'} · Assegna
      </button>
    )
  }
  return (
    <span className="rounded-full bg-card-2 px-2 py-0.5 text-[12px] font-bold whitespace-nowrap text-ink-2">
      {categoryPath(category, lookups.categories)}
    </span>
  )
}

/** Filled = set on this row; outlined = inherited from the category. */
function NecessityCell({ t, lookups }: { t: Transaction; lookups: Lookups }) {
  if (t.type !== 'expense') return <span className="text-ink-3">—</span>
  const { level, source } = transactionNecessity(t, lookups.categories)
  if (!level) {
    return <span className="rounded-full border border-warn px-2 py-px text-[12px] font-bold whitespace-nowrap text-warn">Da classificare</span>
  }
  return source === 'override' ? (
    <span title="Impostato su questo movimento" className="rounded-full bg-bar px-2 py-0.5 text-[12px] font-bold text-card">
      {NECESSITY_LABELS[level]}
      <span className="sr-only"> (impostato sul movimento)</span>
    </span>
  ) : (
    <span title="Ereditato dalla categoria" className="rounded-full border border-field px-2 py-px text-[12px] font-bold text-ink-2">
      {NECESSITY_LABELS[level]}
      <span className="sr-only"> (ereditato dalla categoria)</span>
    </span>
  )
}

function SourceBadge({ t }: { t: Transaction }) {
  if (t.source !== 'import') return null
  return (
    <span title="Importato da CSV" className="rounded bg-card-2 px-1.5 py-px text-[10px] font-extrabold tracking-[0.04em] text-ink-3">
      CSV
    </span>
  )
}

interface DayGroup {
  date: string
  rows: Transaction[]
}

function groupByDay(rows: Transaction[]): DayGroup[] {
  const groups: DayGroup[] = []
  for (const row of rows) {
    const last = groups[groups.length - 1]
    if (last?.date === row.date) last.rows.push(row)
    else groups.push({ date: row.date, rows: [row] })
  }
  return groups
}

function DayTotal({ value, currency }: { value: number | undefined; currency: string }) {
  if (value === undefined) return null
  return (
    <>
      {formatAmount(value, currency, { sign: value > 0 ? 'always' : 'auto' })} {currency}
    </>
  )
}

function TransactionTable({
  groups,
  dayTotals,
  lookups,
  onEdit,
  onDelete,
}: {
  groups: DayGroup[]
  dayTotals: Map<string, number>
  lookups: Lookups
  onEdit: (t: Transaction) => void
  onDelete: (t: Transaction) => void
}) {
  const menu = (t: Transaction) => (
    <RowMenu
      label={`Azioni per ${t.description || 'movimento'}`}
      items={[
        { label: 'Modifica', onSelect: () => onEdit(t) },
        { label: 'Elimina', tone: 'danger', onSelect: () => onDelete(t) },
      ]}
    />
  )

  return (
    <>
      {/* Desktop/tablet: grouped table. */}
      <div className="relative overflow-x-auto max-md:hidden">
        <table className="w-full min-w-[860px] border-collapse tabular-nums">
          <thead>
            <tr className="text-left text-[12px] text-ink-3">
              <th scope="col" className="border-b border-line px-4 py-2.5 font-bold">Descrizione</th>
              <th scope="col" className="border-b border-line px-3 py-2.5 font-bold">Categoria</th>
              <th scope="col" className="border-b border-line px-3 py-2.5 font-bold">Necessità</th>
              <th scope="col" className="border-b border-line px-3 py-2.5 font-bold">Conto</th>
              <th scope="col" className="border-b border-line px-3 py-2.5 text-right font-bold">Importo</th>
              <th scope="col" className="w-14 border-b border-line py-2.5 pr-4 pl-1">
                <span className="sr-only">Azioni</span>
              </th>
            </tr>
          </thead>
          {groups.map((group) => (
            <tbody key={group.date}>
              <tr className="bg-card-2">
                <th scope="rowgroup" colSpan={4} className="px-4 py-2 text-left text-[12px] font-extrabold text-ink-2">
                  {formatDayHeader(group.date)}
                </th>
                <td colSpan={2} className="py-2 pr-[70px] text-right text-[12px] font-bold text-ink-3">
                  <DayTotal value={dayTotals.get(group.date)} currency={lookups.baseCurrency} />
                </td>
              </tr>
              {group.rows.map((t) => (
                <tr key={t.id}>
                  <td className="border-t border-line px-4 py-2.5">
                    <div className="flex items-center gap-2 font-bold">
                      {t.description || '—'}
                      <SourceBadge t={t} />
                    </div>
                  </td>
                  <td className="border-t border-line px-3 py-2.5">
                    <CategoryCell t={t} lookups={lookups} onAssign={() => onEdit(t)} />
                  </td>
                  <td className="border-t border-line px-3 py-2.5">
                    <NecessityCell t={t} lookups={lookups} />
                  </td>
                  <td className="border-t border-line px-3 py-2.5 text-[13px] text-ink-2">
                    {accountLabel(t, lookups.accounts)}
                  </td>
                  <td className="border-t border-line px-3 py-2.5 text-right">
                    <Amount
                      value={t.amount}
                      currency={t.currency}
                      baseValue={t.amount_base_currency}
                      baseCurrency={lookups.baseCurrency}
                      kind={amountKind(t)}
                    />
                  </td>
                  <td className="border-t border-line py-1 pr-4 pl-1">{menu(t)}</td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>

      {/* Phones: one card-list per day, as in D-Transazioni-Mobile. */}
      <div className="md:hidden">
        {groups.map((group) => (
          <section key={group.date} aria-label={formatDayHeader(group.date)}>
            <div className="flex justify-between bg-card-2 px-3.5 py-2 text-[12px] font-extrabold text-ink-2 tabular-nums">
              <span>{formatDayHeader(group.date)}</span>
              <span className="text-ink-3">
                <DayTotal value={dayTotals.get(group.date)} currency={lookups.baseCurrency} />
              </span>
            </div>
            <ul>
              {group.rows.map((t) => (
                <li key={t.id} className="flex items-center gap-1 border-t border-line py-1.5 pr-1 pl-3.5">
                  <div className="min-w-0 flex-1 py-1">
                    <div className="flex items-center gap-1.5 font-bold">
                      <span className="truncate">{t.description || '—'}</span>
                      <SourceBadge t={t} />
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <CategoryCell t={t} lookups={lookups} onAssign={() => onEdit(t)} />
                      {t.counterpart_account_id && <span className="text-[12px] text-ink-3">{accountLabel(t, lookups.accounts)}</span>}
                    </div>
                  </div>
                  <Amount
                    value={t.amount}
                    currency={t.currency}
                    baseValue={t.amount_base_currency}
                    baseCurrency={lookups.baseCurrency}
                    kind={amountKind(t)}
                  />
                  {menu(t)}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  )
}

function FilterChip({ children, onRemove, label }: { children: ReactNode; onRemove: () => void; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-accent bg-accent-soft py-0.5 pr-0.5 pl-3 text-[13px] font-bold text-accent">
      {children}
      <button type="button" onClick={onRemove} aria-label={`Rimuovi filtro ${label}`} className="grid h-8 w-8 cursor-pointer place-items-center rounded-full hover:bg-card">
        ✕
      </button>
    </span>
  )
}

type FilterPatch = Partial<Record<keyof TransactionFilters | 'import' | 'new', string | null>>

const filterLabel = 'flex min-w-0 flex-col gap-1 text-[12px] font-bold text-ink-3'

export function TransactionsPage() {
  const { user } = useAuth()
  const baseCurrency = user?.base_currency ?? ''
  const [params, setParams] = useSearchParams()
  const filters = readFilters(params)
  const [today] = useState(() => new Date())
  const [editing, setEditing] = useState<Transaction | null>(null)
  const [deleting, setDeleting] = useState<Transaction | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const deleteTransaction = useDeleteTransaction()

  function update(patch: FilterPatch, { keepPage = false } = {}) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(patch)) {
          if (value === null || value === '') next.delete(key)
          else next.set(key, value)
        }
        if (!keepPage && !('page' in patch)) next.delete('page')
        return next
      },
      // Typing in the search box shouldn't add a history entry per keystroke.
      { replace: 'q' in patch },
    )
  }

  const apiFilters = {
    ...periodRange(filters.period, today),
    account_id: filters.account || undefined,
    category_id: filters.category || undefined,
    currency: filters.currency || undefined,
    type: filters.type || undefined,
    merge_transfer_legs: true,
  }

  // The API filters and paginates by itself, except for text search and
  // "only Varie": those fall back to filtering the whole period here.
  // The full set is fetched either way, for the summary and day totals.
  const clientSide = !!filters.q.trim() || filters.misc
  const all = useAllTransactions(apiFilters)
  const paged = useTransactionsList({ ...apiFilters, page: filters.page, page_size: filters.size }, !clientSide)

  const lookups: Lookups = { categories: indexById(categories), accounts: indexById(accounts), baseCurrency }
  const needle = filters.q.trim().toLowerCase()
  const matching = (all.data ?? []).filter((t) => {
    if (filters.misc && !(t.type !== 'transfer' && isMiscCategory(lookups.categories.get(t.category_id ?? '')))) return false
    if (!needle) return true
    const category = lookups.categories.get(t.category_id ?? '')
    return [t.description, category?.name, t.amount, formatAmount(t.amount, t.currency, { sign: 'never' })]
      .filter(Boolean)
      .some((field) => String(field).toLowerCase().includes(needle))
  })

  const totalItems = clientSide ? matching.length : (paged.data?.meta.total_items ?? 0)
  const totalPages = Math.max(1, Math.ceil(totalItems / filters.size))
  const rows = clientSide ? matching.slice((filters.page - 1) * filters.size, filters.page * filters.size) : (paged.data?.data ?? [])
  const isLoading = clientSide ? all.isLoading : paged.isLoading
  const isError = clientSide ? all.isError : paged.isError

  const sum = totals(matching)
  const dayTotals = new Map<string, number>()
  for (const t of matching) {
    // Transfers net to zero across your own accounts; leave them out of the day's figure.
    if (t.type === 'transfer') continue
    dayTotals.set(t.date, (dayTotals.get(t.date) ?? 0) + Number(t.amount_base_currency))
  }
  const misc = (all.data ?? []).filter((t) => t.type !== 'transfer' && isMiscCategory(lookups.categories.get(t.category_id ?? '')))
  const miscSum = misc.reduce((s, t) => s + Number(t.amount_base_currency), 0)

  const currencies = [...new Set((accounts ?? []).map((a) => a.currency))].sort()
  const chips: { key: string; label: string; text: string; clear: FilterPatch }[] = []
  if (filters.period !== 'all') chips.push({ key: 'period', label: 'periodo', text: `Periodo: ${PERIOD_LABELS[filters.period]}`, clear: { period: 'all' } })
  if (filters.account) chips.push({ key: 'account', label: 'conto', text: `Conto: ${lookups.accounts.get(filters.account)?.name ?? '—'}`, clear: { account: null } })
  if (filters.category) chips.push({ key: 'category', label: 'categoria', text: `Categoria: ${lookups.categories.get(filters.category)?.name ?? '—'}`, clear: { category: null } })
  if (filters.currency) chips.push({ key: 'currency', label: 'valuta', text: `Valuta: ${filters.currency}`, clear: { currency: null } })
  if (filters.type) chips.push({ key: 'type', label: 'tipo', text: TYPE_LABELS[filters.type], clear: { type: null } })
  if (filters.misc) chips.push({ key: 'misc', label: 'da assegnare', text: 'Solo da assegnare (Varie)', clear: { misc: null } })
  if (filters.q) chips.push({ key: 'q', label: 'ricerca', text: `“${filters.q}”`, clear: { q: null } })

  const importOpen = params.get('import') === '1'
  const creating = params.get('new') === '1'

  async function confirmDelete() {
    if (!deleting) return
    setDeleteError(null)
    try {
      await deleteTransaction.mutateAsync(deleting.id)
      setDeleting(null)
    } catch (error) {
      setDeleteError(apiErrorMessage(error))
    }
  }

  return (
    <>
      <PageHeader
        title="Transazioni"
        subtitle={`${sum.count} movimenti ${periodPhrase(filters.period, today)} · importi in valuta originale, totali in ${baseCurrency}`}
        actions={
          <>
            <Button
              aria-expanded={importOpen}
              onClick={() => update({ import: importOpen ? null : '1' }, { keepPage: true })}
              className={importOpen ? 'border-accent bg-accent-soft text-accent' : ''}
            >
              <UploadIcon />
              Importa CSV
            </Button>
            <Button variant="primary" onClick={() => update({ new: '1' }, { keepPage: true })}>
              + Nuova transazione
            </Button>
          </>
        }
      />

      {importOpen && <TransactionImport onDone={() => update({ import: null }, { keepPage: true })} />}

      <section aria-label="Filtri" className="flex flex-col gap-3 rounded-[14px] border border-line bg-card px-4 py-3.5">
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-[minmax(220px,2fr)_repeat(4,minmax(0,1fr))]">
          <label className={`${filterLabel} col-span-2 md:col-span-1`}>
            Cerca
            <span className="flex min-h-11 items-center gap-2 rounded-[10px] border border-field bg-card px-3 text-ink-3 focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--color-accent-soft)]">
              <SearchIcon />
              <input
                type="search"
                value={filters.q}
                onChange={(e) => update({ q: e.target.value })}
                placeholder="Descrizione, importo, categoria…"
                className="min-w-0 flex-1 bg-transparent text-[14px] font-normal text-ink outline-none placeholder:text-ink-3"
              />
            </span>
          </label>
          <label className={filterLabel}>
            Periodo
            <select value={filters.period} onChange={(e) => update({ period: e.target.value })} className="field text-[14px] font-normal">
              {(Object.keys(PERIOD_LABELS) as PeriodKey[]).map((p) => (
                <option key={p} value={p}>
                  {PERIOD_LABELS[p]}
                </option>
              ))}
            </select>
          </label>
          <label className={filterLabel}>
            Conto
            <select value={filters.account} onChange={(e) => update({ account: e.target.value })} className="field text-[14px] font-normal">
              <option value="">Tutti i conti</option>
              {accounts?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className={filterLabel}>
            Categoria
            <CategorySelect
              categories={categories}
              emptyLabel="Tutte"
              value={filters.category}
              onChange={(e) => update({ category: e.target.value })}
              className="field text-[14px] font-normal"
            />
          </label>
          <label className={filterLabel}>
            Valuta
            <select value={filters.currency} onChange={(e) => update({ currency: e.target.value })} className="field text-[14px] font-normal">
              <option value="">Tutte</option>
              {currencies.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2.5">
          <SegmentedControl label="Tipo di movimento" options={TYPE_OPTIONS} value={filters.type} onChange={(type) => update({ type })} />
          {chips.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {chips.map((chip) => (
                <FilterChip key={chip.key} label={chip.label} onRemove={() => update(chip.clear)}>
                  {chip.text}
                </FilterChip>
              ))}
              <button type="button" onClick={() => setParams(new URLSearchParams())} className="link min-h-11 cursor-pointer px-1 text-[13px]">
                Azzera filtri
              </button>
            </div>
          )}
        </div>
      </section>

      <section
        aria-label="Riepilogo del filtro"
        className="grid overflow-hidden rounded-[14px] border border-line bg-card tabular-nums"
        style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(150px, 100%), 1fr))' }}
      >
        {[
          { label: 'Movimenti', value: String(sum.count), tone: 'text-ink' },
          { label: 'Entrate', value: `${formatAmount(sum.income, baseCurrency, { sign: 'always' })}`, tone: 'text-pos' },
          { label: 'Uscite', value: formatAmount(sum.expense, baseCurrency), tone: 'text-ink' },
          { label: 'Trasferimenti', value: `⇄ ${sum.transferCount}`, tone: 'text-ink-3' },
          { label: 'Saldo', value: formatAmount(sum.net, baseCurrency, { sign: 'always' }), tone: sum.net < 0 ? 'text-neg' : 'text-ink' },
        ].map((item) => (
          <div key={item.label} className="px-4 py-3 shadow-[-1px_0_0_var(--color-line),0_-1px_0_var(--color-line)]">
            <div className="text-[12px] font-bold text-ink-3">{item.label}</div>
            <div className={`text-[17px] font-extrabold ${item.tone}`}>
              {item.value}
              {item.label !== 'Movimenti' && item.label !== 'Trasferimenti' && <span className="ccy ml-1">{baseCurrency}</span>}
            </div>
          </div>
        ))}
      </section>

      {misc.length > 0 && !filters.misc && (
        <Notice
          action={
            <button type="button" onClick={() => update({ misc: '1' })} className="min-h-8 cursor-pointer text-warn underline">
              Mostra solo questi
            </button>
          }
        >
          {misc.length} {misc.length === 1 ? 'movimento è' : 'movimenti sono'} in Varie ({formatAmount(miscSum, baseCurrency)} {baseCurrency}): assegna una
          categoria perché contino nel piano giusto.
        </Notice>
      )}

      <section aria-label="Elenco movimenti" className="overflow-hidden rounded-[14px] border border-line bg-card">
        {isLoading ? (
          <LoadingBlock className="m-4 h-64" />
        ) : isError ? (
          <div className="p-4">
            <ErrorBlock>Errore nel caricamento delle transazioni.</ErrorBlock>
          </div>
        ) : rows.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="Nessun movimento"
              action={chips.length > 0 ? <Button onClick={() => setParams(new URLSearchParams())}>Azzera filtri</Button> : undefined}
            >
              {chips.length > 0 ? 'Nessun movimento corrisponde ai filtri attivi.' : 'Aggiungi una transazione o importa un CSV.'}
            </EmptyState>
          </div>
        ) : (
          <TransactionTable
            groups={groupByDay(rows)}
            dayTotals={dayTotals}
            lookups={lookups}
            onEdit={setEditing}
            onDelete={(t) => {
              setDeleteError(null)
              setDeleting(t)
            }}
          />
        )}
        {totalItems > 0 && (
          <Pagination
            page={Math.min(filters.page, totalPages)}
            totalPages={totalPages}
            totalItems={totalItems}
            pageSize={filters.size}
            pageSizes={PAGE_SIZES}
            onPage={(page) => update({ page: String(page) })}
            onPageSize={(size) => update({ size: String(size) })}
          />
        )}
      </section>

      <TransactionFormDialog open={creating} onClose={() => update({ new: null }, { keepPage: true })} />
      <TransactionFormDialog open={!!editing} onClose={() => setEditing(null)} transaction={editing} />
      <ConfirmDialog
        open={!!deleting}
        title="Eliminare questo movimento?"
        confirmLabel="Elimina"
        pending={deleteTransaction.isPending}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      >
        <b>{deleting?.description || 'Movimento senza descrizione'}</b>
        {deleting && ` · ${formatAmount(deleting.amount, deleting.currency)} ${deleting.currency}`}
        {deleting?.counterpart_transaction_id && (
          <p className="mt-2">È un giroconto: verrà eliminato anche il movimento collegato sull'altro conto.</p>
        )}
      </ConfirmDialog>
    </>
  )
}
