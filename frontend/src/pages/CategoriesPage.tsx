import { Fragment, useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { PlusIcon } from '@/components/ui/Icon'
import { PageHeader } from '@/components/ui/PageHeader'
import { RowMenu } from '@/components/ui/RowMenu'
import { useAuth } from '@/hooks/useAuth'
import { useCategories, useCreateCategory, useDeleteCategory, useUpdateCategory } from '@/hooks/useCategories'
import { useAllocationStatus } from '@/hooks/usePlanning'
import { useTransactionSummary } from '@/hooks/useTransactions'
import { apiErrorMessage } from '@/lib/apiError'
import {
  CATEGORY_TYPE_LABELS,
  categoryNecessity,
  categoryTree,
  indexById,
  NECESSITY_LABELS,
  unclassifiedExpenseCategories,
} from '@/lib/categories'
import { addMonths, endOfMonth, monthRange } from '@/lib/dates'
import { formatAmount, formatMonthName, formatPercent, toISODate, toNumber } from '@/lib/format'
import type { Category, CategoryType, NecessityLevel } from '@/types'

const TABS: CategoryType[] = ['expense', 'income', 'transfer']
const LEVELS: NecessityLevel[] = ['primary', 'useful', 'discretionary']
const AVERAGE_MONTHS = 6

const NEW_PLACEHOLDER: Record<CategoryType, string> = {
  expense: 'Es. Animali domestici',
  income: 'Es. Dividendi',
  transfer: 'Es. Giroconto',
}

const NEW_LABEL: Record<CategoryType, string> = {
  expense: 'Nuova categoria di spesa',
  income: 'Nuova categoria di entrata',
  transfer: 'Nuova categoria di trasferimento',
}

/** Spend per category: this month and the average over the previous whole months. */
function useCategoryAmounts(today: Date) {
  const month = useTransactionSummary({ group_by: ['category'], ...monthRange(today) })
  const history = useTransactionSummary({
    group_by: ['category'],
    date_from: toISODate(addMonths(today, -AVERAGE_MONTHS)),
    date_to: toISODate(endOfMonth(addMonths(today, -1))),
  })
  const toMap = (rows: { category_id: string | null; total_amount_base_currency: string }[] | undefined) =>
    new Map((rows ?? []).map((r) => [r.category_id ?? '', toNumber(r.total_amount_base_currency)]))
  return { month: toMap(month.data?.data), history: toMap(history.data?.data) }
}

function LevelPicker({
  category,
  byId,
  onChange,
  disabled,
}: {
  category: Category
  byId: Map<string, Category>
  onChange: (level: NecessityLevel | null) => void
  disabled: boolean
}) {
  const parent = category.parent_id ? byId.get(category.parent_id) : undefined
  const options: { value: NecessityLevel | null; label: string }[] = LEVELS.map((level) => ({ value: level, label: NECESSITY_LABELS[level] }))
  // Subcategories can go back to inheriting; the option names what they'd get.
  if (parent) {
    options.unshift({
      value: null,
      label: parent.necessity_level ? `Eredita · ${NECESSITY_LABELS[parent.necessity_level]}` : 'Eredita · nessuno',
    })
  }
  return (
    <div role="radiogroup" aria-label={`Livello di necessità di ${category.name}`} className="inline-flex flex-wrap gap-0.5 rounded-[10px] bg-card-2 p-[3px]">
      {options.map((option) => {
        const on = category.necessity_level === option.value
        return (
          <button
            key={option.label}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => !on && onChange(option.value)}
            className={`min-h-9 cursor-pointer rounded-lg px-2.5 text-[13px] whitespace-nowrap disabled:cursor-wait ${
              on ? 'bg-card font-extrabold text-ink shadow-[0_1px_2px_rgba(0,0,0,0.14)]' : 'font-semibold text-ink-2 hover:text-ink'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

function IncomeBaseSwitch({ category, onChange, disabled }: { category: Category; onChange: (excluded: boolean) => void; disabled: boolean }) {
  const counts = !category.excluded_from_income_base
  return (
    <button
      type="button"
      role="switch"
      aria-checked={counts}
      aria-label={`${category.name}: conta nella base del piano`}
      disabled={disabled}
      onClick={() => onChange(counts)}
      className="inline-flex min-h-11 cursor-pointer items-center gap-2.5 text-[13px] font-bold"
    >
      <span className={`relative h-6 w-10 rounded-full transition-colors ${counts ? 'bg-accent' : 'bg-field'}`}>
        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-card shadow transition-[left] ${counts ? 'left-[18px]' : 'left-0.5'}`} />
      </span>
      {counts ? 'Conta nella base' : 'Esclusa (rimborso/storno)'}
    </button>
  )
}

function NameDialog({
  open,
  title,
  initial,
  confirmLabel,
  onSubmit,
  onClose,
}: {
  open: boolean
  title: string
  initial: string
  confirmLabel: string
  onSubmit: (name: string) => Promise<void>
  onClose: () => void
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title}>
      {open && <NameForm initial={initial} confirmLabel={confirmLabel} onSubmit={onSubmit} onClose={onClose} />}
    </Dialog>
  )
}

function NameForm({ initial, confirmLabel, onSubmit, onClose }: { initial: string; confirmLabel: string; onSubmit: (name: string) => Promise<void>; onClose: () => void }) {
  const [name, setName] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return setError('Il nome è obbligatorio')
    setPending(true)
    try {
      await onSubmit(name.trim())
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e))
    } finally {
      setPending(false)
    }
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Field label="Nome" htmlFor="category-name" error={error ?? undefined}>
        <input id="category-name" autoFocus className="field" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!error} />
      </Field>
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button type="submit" variant="primary" disabled={pending}>
          {confirmLabel}
        </Button>
      </div>
    </form>
  )
}

function MoveDialog({ category, categories, onClose }: { category: Category | null; categories: Category[]; onClose: () => void }) {
  const updateCategory = useUpdateCategory()
  const [parentId, setParentId] = useState(category?.parent_id ?? '')
  const [error, setError] = useState<string | null>(null)
  if (!category) return <Dialog open={false} onClose={onClose} title="" />
  const hasChildren = categories.some((c) => c.parent_id === category.id && !c.deleted_at)
  // One level deep: only roots of the same type, and not itself.
  const targets = categories.filter((c) => c.type === category.type && c.parent_id === null && c.id !== category.id && !c.deleted_at)
  async function save() {
    setError(null)
    try {
      await updateCategory.mutateAsync({ id: category!.id, payload: { parent_id: parentId || null } })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Spostamento non riuscito.'))
    }
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Sposta “${category.name}”`}
      description="Le sottocategorie stanno sotto una categoria principale dello stesso tipo."
      footer={
        <>
          <Button onClick={onClose}>Annulla</Button>
          <Button variant="primary" onClick={save} disabled={hasChildren || updateCategory.isPending}>
            Sposta
          </Button>
        </>
      }
    >
      {hasChildren ? (
        <ErrorBlock>Ha delle sottocategorie: spostale prima, poi potrai spostare questa.</ErrorBlock>
      ) : (
        <Field label="Nuova posizione" htmlFor="move-parent">
          <select id="move-parent" className="field" value={parentId} onChange={(e) => setParentId(e.target.value)}>
            <option value="">Categoria principale</option>
            {targets.map((t) => (
              <option key={t.id} value={t.id}>
                Sotto “{t.name}”
              </option>
            ))}
          </select>
        </Field>
      )}
      {error && <ErrorBlock>{error}</ErrorBlock>}
    </Dialog>
  )
}

function CoverageCard({ today }: { today: Date }) {
  const { data: status } = useAllocationStatus(toISODate(today))
  const { data: categories } = useCategories()
  const todo = unclassifiedExpenseCategories(categories).length
  if (!status) return <LoadingBlock className="h-36 flex-[999_1_480px]" />
  const amount = (bucket: string) => toNumber(status.buckets.find((b) => b.bucket === bucket)?.actual_amount)
  // Monochrome on purpose: these are levels of one scale, not identities,
  // and the unclassified slot gets the amber "attention" treatment.
  const parts = [
    { label: 'Primarie', value: amount('primary'), className: 'bg-ink' },
    { label: 'Utili', value: amount('useful'), className: 'bg-ink-2' },
    { label: 'Accessorie', value: amount('discretionary'), className: 'bg-ink-3' },
    { label: 'Non classificate', value: toNumber(status.unclassified_amount), className: 'bg-warn' },
  ]
  const spend = parts.reduce((s, p) => s + p.value, 0)
  const base = status.base_currency
  return (
    <section aria-label="Copertura della classificazione" className="flex-[999_1_480px] rounded-[14px] border border-line bg-card px-5 py-4 tabular-nums">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <span className="text-[26px] font-extrabold">{spend ? formatPercent(status.classification_coverage, { digits: 0 }) : '—'}</span>{' '}
          <span className="font-semibold text-ink-2">della spesa di {formatMonthName(today)} è classificata</span>
        </div>
        {todo > 0 && (
          <span className="rounded-full bg-warn-soft px-2.5 py-1 text-[13px] font-bold text-warn">
            {todo} {todo === 1 ? 'categoria' : 'categorie'} da classificare · {formatAmount(status.unclassified_amount, base)} {base}
          </span>
        )}
      </div>
      {spend > 0 ? (
        <>
          <div className="mt-3 flex h-3 gap-0.5" aria-hidden="true">
            {parts
              .filter((p) => p.value > 0)
              .map((p) => (
                <span key={p.label} className={`min-w-1 rounded-[3px] ${p.className}`} style={{ flex: `${p.value} 1 0` }} />
              ))}
          </div>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
            {parts.map((p) => (
              <li key={p.label} className="inline-flex items-center gap-1.5">
                <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-[3px] ${p.className}`} />
                {p.label} <b className="text-ink">{formatAmount(p.value, base)}</b>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-2 text-[13px] text-ink-3">Nessuna spesa registrata questo mese.</p>
      )}
    </section>
  )
}

function QuickAdd({ type }: { type: CategoryType }) {
  const createCategory = useCreateCategory()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    setError(null)
    try {
      await createCategory.mutateAsync({ name: name.trim(), type, parent_id: null })
      setName('')
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }
  return (
    <form aria-label="Nuova categoria" onSubmit={submit} className="flex flex-[1_1_300px] flex-col gap-2 rounded-[14px] border border-line bg-card px-5 py-4">
      <label htmlFor={`new-cat-${type}`} className="text-[13px] font-extrabold">
        {NEW_LABEL[type]}
      </label>
      <div className="flex gap-2">
        <input id={`new-cat-${type}`} value={name} onChange={(e) => setName(e.target.value)} placeholder={NEW_PLACEHOLDER[type]} className="field min-w-0 flex-1" />
        <Button type="submit" variant="primary" disabled={createCategory.isPending || !name.trim()}>
          Aggiungi
        </Button>
      </div>
      {error ? <ErrorBlock>{error}</ErrorBlock> : <p className="text-[12px] text-ink-3">Per una sottocategoria usa «+» sulla riga della categoria madre.</p>}
    </form>
  )
}

function CategoryTable({ type, categories, today, baseCurrency }: { type: CategoryType; categories: Category[]; today: Date; baseCurrency: string }) {
  const updateCategory = useUpdateCategory()
  const createCategory = useCreateCategory()
  const deleteCategory = useDeleteCategory()
  const amounts = useCategoryAmounts(today)
  const byId = indexById(categories)
  const [onlyTodo, setOnlyTodo] = useState(false)
  const [renaming, setRenaming] = useState<Category | null>(null)
  const [moving, setMoving] = useState<Category | null>(null)
  const [addingTo, setAddingTo] = useState<Category | null>(null)
  const [deleting, setDeleting] = useState<Category | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [rowError, setRowError] = useState<string | null>(null)

  const isTodo = (c: Category) => type === 'expense' && categoryNecessity(c, byId).level === null
  const tree = categoryTree(categories, type).filter(({ parent, children }) => !onlyTodo || isTodo(parent) || children.some(isTodo))

  const monthOf = (c: Category, children: Category[] = []) =>
    [c, ...children].reduce((s, x) => s + (amounts.month.get(x.id) ?? 0), 0)
  const avgOf = (c: Category, children: Category[] = []) =>
    [c, ...children].reduce((s, x) => s + (amounts.history.get(x.id) ?? 0), 0) / AVERAGE_MONTHS

  async function update(id: string, payload: Parameters<typeof updateCategory.mutateAsync>[0]['payload']) {
    setRowError(null)
    try {
      await updateCategory.mutateAsync({ id, payload })
    } catch (e) {
      setRowError(apiErrorMessage(e))
    }
  }

  async function confirmDelete() {
    if (!deleting) return
    setDeleteError(null)
    try {
      await deleteCategory.mutateAsync(deleting.id)
      setDeleting(null)
    } catch (e) {
      // 409 when it still has active subcategories — the backend's message says so.
      setDeleteError(apiErrorMessage(e, 'Impossibile eliminare la categoria.'))
    }
  }

  const money = (value: number) => (value ? formatAmount(type === 'expense' ? Math.abs(value) : value, baseCurrency) : '—')

  function row(category: Category, children: Category[], depth: 0 | 1) {
    const todo = isTodo(category)
    const nameCell = (
      <th scope="row" className={`py-2.5 text-left font-normal md:border-t md:border-line ${depth ? 'pr-3 pl-8 md:pl-12' : 'px-4 sm:px-5'}`}>
        <span className={depth ? 'font-semibold text-ink-2' : 'font-extrabold'}>
          {depth ? <span aria-hidden="true" className="mr-1.5 text-ink-3">└</span> : null}
          {category.name}
        </span>{' '}
        {todo && <span className="ml-1 rounded-full border border-warn px-2 py-px text-[11px] font-bold whitespace-nowrap text-warn">Da classificare</span>}
        {depth === 0 && children.length > 0 && (
          <div className="text-[12px] font-medium text-ink-3">
            {children.length} {children.length === 1 ? 'sottocategoria' : 'sottocategorie'}
          </div>
        )}
      </th>
    )
    return (
      // Below md each row reflows into a small card: name + actions, then the picker, then the amounts.
      <tr key={category.id} className={`max-md:grid max-md:grid-cols-[1fr_auto] max-md:items-center max-md:border-t max-md:border-line max-md:pb-3 ${depth ? 'bg-card-2/50' : ''}`}>
        {nameCell}
        <td className="px-3 py-2 max-md:col-span-2 max-md:row-start-2 max-md:px-4 max-md:py-1 md:border-t md:border-line">
          {type === 'expense' && (
            <LevelPicker category={category} byId={byId} disabled={updateCategory.isPending} onChange={(level) => update(category.id, { necessity_level: level })} />
          )}
          {type === 'income' && (
            <IncomeBaseSwitch category={category} disabled={updateCategory.isPending} onChange={(excluded) => update(category.id, { excluded_from_income_base: excluded })} />
          )}
          {type === 'transfer' && <span className="text-[13px] text-ink-3">Fuori dal piano</span>}
        </td>
        <td className="px-3 py-2 text-right font-bold max-md:col-span-2 max-md:px-4 max-md:py-0.5 max-md:text-left max-md:text-[13px] md:border-t md:border-line">
          <span className="font-semibold text-ink-3 capitalize md:hidden">{formatMonthName(today)}: </span>
          {money(monthOf(category, children))}
        </td>
        <td className="px-3 py-2 text-right text-ink-2 max-md:col-span-2 max-md:px-4 max-md:py-0.5 max-md:text-left max-md:text-[13px] md:border-t md:border-line">
          <span className="font-semibold text-ink-3 md:hidden">Media {AVERAGE_MONTHS} mesi: </span>
          {money(avgOf(category, children))}
        </td>
        <td className="py-1 pr-4 pl-2 max-md:col-start-2 max-md:row-start-1 md:border-t md:border-line">
          <div className="flex justify-end gap-0.5">
            {depth === 0 && (
              <button
                type="button"
                aria-label={`Aggiungi sottocategoria a ${category.name}`}
                onClick={() => setAddingTo(category)}
                className="grid h-11 w-11 cursor-pointer place-items-center rounded-[10px] text-ink-2 hover:bg-card-2"
              >
                <PlusIcon className="h-[18px] w-[18px]" />
              </button>
            )}
            <RowMenu
              label={`Azioni per ${category.name}`}
              items={[
                { label: 'Rinomina', onSelect: () => setRenaming(category) },
                { label: 'Sposta…', onSelect: () => setMoving(category) },
                {
                  label: 'Elimina',
                  tone: 'danger',
                  onSelect: () => {
                    setDeleteError(null)
                    setDeleting(category)
                  },
                },
              ]}
            />
          </div>
        </td>
      </tr>
    )
  }

  const levelHeader = type === 'expense' ? 'Livello di necessità' : type === 'income' ? 'Base del piano' : 'Piano'

  return (
    <section aria-label={`Categorie: ${CATEGORY_TYPE_LABELS[type]}`} className="overflow-hidden rounded-[14px] border border-line bg-card">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line px-4 py-2.5 sm:px-5">
        {type === 'expense' ? (
          <>
            <label className="flex min-h-11 cursor-pointer items-center gap-2 text-[14px] font-semibold">
              <input type="checkbox" checked={onlyTodo} onChange={(e) => setOnlyTodo(e.target.checked)} className="h-[18px] w-[18px] accent-accent" />
              Mostra solo da classificare
            </label>
            <span className="text-[12px] text-ink-3">Le sottocategorie ereditano il livello della madre, se non lo imposti</span>
          </>
        ) : (
          <p className="py-2 text-[13px] text-ink-2">
            {type === 'income'
              ? 'Le entrate escluse (rimborsi, storni) non contano nella base su cui il piano calcola le percentuali.'
              : 'I trasferimenti spostano denaro tra i tuoi conti: non sono né entrate né uscite e non entrano nel piano.'}
          </p>
        )}
      </div>
      {rowError && (
        <div className="px-4 pt-3 sm:px-5">
          <ErrorBlock>{rowError}</ErrorBlock>
        </div>
      )}
      {tree.length === 0 ? (
        <div className="p-4">
          <EmptyState title={onlyTodo ? 'Tutto classificato' : 'Nessuna categoria'}>
            {onlyTodo ? 'Ogni categoria di spesa ha un livello di necessità.' : 'Aggiungine una con il campo qui sopra.'}
          </EmptyState>
        </div>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full border-collapse tabular-nums max-md:block md:min-w-[820px]">
            <thead className="max-md:hidden">
              <tr className="text-left text-[12px] text-ink-3">
                <th scope="col" className="px-4 py-2.5 font-bold sm:px-5">Categoria</th>
                <th scope="col" className="px-3 py-2.5 font-bold">{levelHeader}</th>
                <th scope="col" className="px-3 py-2.5 text-right font-bold capitalize">{formatMonthName(today)}</th>
                <th scope="col" className="px-3 py-2.5 text-right font-bold">Media {AVERAGE_MONTHS} mesi</th>
                <th scope="col" className="w-[110px] py-2.5 pr-4 pl-2">
                  <span className="sr-only">Azioni</span>
                </th>
              </tr>
            </thead>
            <tbody className="max-md:block">
              {tree.map(({ parent, children }) => (
                <Fragment key={parent.id}>
                  {row(parent, children, 0)}
                  {children.filter((c) => !onlyTodo || isTodo(c) || isTodo(parent)).map((child) => row(child, [], 1))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <NameDialog
        open={!!renaming}
        title="Rinomina categoria"
        initial={renaming?.name ?? ''}
        confirmLabel="Salva"
        onClose={() => setRenaming(null)}
        onSubmit={async (name) => {
          await updateCategory.mutateAsync({ id: renaming!.id, payload: { name } })
        }}
      />
      <NameDialog
        open={!!addingTo}
        title={`Nuova sottocategoria di “${addingTo?.name ?? ''}”`}
        initial=""
        confirmLabel="Aggiungi"
        onClose={() => setAddingTo(null)}
        onSubmit={async (name) => {
          await createCategory.mutateAsync({ name, type, parent_id: addingTo!.id })
        }}
      />
      <MoveDialog key={moving?.id} category={moving} categories={categories} onClose={() => setMoving(null)} />
      <ConfirmDialog
        open={!!deleting}
        title={`Eliminare “${deleting?.name}”?`}
        confirmLabel="Elimina"
        pending={deleteCategory.isPending}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      >
        I movimenti già registrati la mantengono e la mostrano come eliminata.
      </ConfirmDialog>
    </section>
  )
}

export function CategoriesPage() {
  const { user } = useAuth()
  const [today] = useState(() => new Date())
  const [tab, setTab] = useState<CategoryType>('expense')
  const { data: categories, isLoading, isError } = useCategories()
  const all = categories ?? []

  return (
    <>
      <PageHeader
        title="Categorie"
        subtitle="Il livello di necessità decide in quale voce del piano finisce ogni spesa"
        actions={
          <div role="tablist" aria-label="Tipo di categoria" className="inline-flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-card-2 p-1">
            {TABS.map((t) => {
              const count = all.filter((c) => c.type === t).length
              const on = t === tab
              return (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  id={`tab-${t}`}
                  aria-selected={on}
                  aria-controls="categories-panel"
                  onClick={() => setTab(t)}
                  className={`flex min-h-10 flex-none cursor-pointer items-center gap-1.5 rounded-[9px] px-3.5 text-[14px] ${
                    on ? 'bg-card font-extrabold text-ink shadow-[0_1px_2px_rgba(0,0,0,0.14)]' : 'font-semibold text-ink-2'
                  }`}
                >
                  {CATEGORY_TYPE_LABELS[t]}
                  <span className="rounded-full bg-bg px-1.5 text-[12px] font-bold text-ink-3 tabular-nums">{count}</span>
                </button>
              )
            })}
          </div>
        }
      />

      <div id="categories-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-4">
          {tab === 'expense' && <CoverageCard today={today} />}
          <QuickAdd key={tab} type={tab} />
        </div>
        {isLoading ? (
          <LoadingBlock className="h-64" />
        ) : isError ? (
          <ErrorBlock>Errore nel caricamento delle categorie.</ErrorBlock>
        ) : (
          <CategoryTable key={tab} type={tab} categories={all} today={today} baseCurrency={user?.base_currency ?? ''} />
        )}
      </div>
    </>
  )
}
