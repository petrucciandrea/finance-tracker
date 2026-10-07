import { useId, useState } from 'react'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { Button } from '@/components/ui/Button'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { CheckIcon } from '@/components/ui/Icon'
import { StatusChip } from '@/components/ui/StatusChip'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import { useConfirmImport, useImportPreview, useUpdateTransaction } from '@/hooks/useTransactions'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatShortDate } from '@/lib/format'
import type { Transaction, TransactionImportPreview, TransactionImportRow } from '@/types'

const STEPS = ['Conto e file', 'Anteprima e categorie', 'Conferma'] as const

function rowStatus(row: TransactionImportRow) {
  if (!row.is_parsable) return <StatusChip kind="over">✕ Non valida</StatusChip>
  if (row.is_duplicate) return <StatusChip kind="warn">⧉ Possibile duplicato</StatusChip>
  return <StatusChip kind="good">✓ Pronta</StatusChip>
}

// The confirm endpoint only takes row numbers and files each row under its
// suggested category. A category changed in the preview is applied right
// after with a PATCH, so each created transaction has to be matched back to
// its row — by content, since rows the backend skips (no exchange rate)
// would shift any index-based mapping.
const rowKey = (date: string, amount: string | number, currency: string, description: string | null) =>
  `${date}|${Number(amount)}|${currency}|${description ?? ''}`

function Stepper({ step }: { step: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-[13px] font-bold">
      {STEPS.map((label, i) => (
        <li key={label} aria-current={i === step ? 'step' : undefined} className={`flex items-center gap-1.5 ${i === step ? 'text-ink' : 'text-ink-3'}`}>
          {i > 0 && (
            <span aria-hidden="true" className="mr-1.5 text-ink-3">
              —
            </span>
          )}
          <span
            aria-hidden="true"
            className={`grid h-[22px] w-[22px] place-items-center rounded-full text-[12px] ${
              i < step ? 'bg-pos-soft text-pos' : i === step ? 'bg-accent text-on-accent' : 'bg-card-2 text-ink-3'
            }`}
          >
            {i < step ? <CheckIcon className="h-3 w-3" /> : i + 1}
          </span>
          {label}
          {i < step && <span className="sr-only"> (completato)</span>}
        </li>
      ))}
    </ol>
  )
}

/** Three-step CSV import: account + file → preview with editable categories → result. */
export function TransactionImport({ onDone }: { onDone: () => void }) {
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const [accountId, setAccountId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<TransactionImportPreview | null>(null)
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set())
  const [categoryEdits, setCategoryEdits] = useState<Map<number, string>>(new Map())
  const [result, setResult] = useState<{ imported: number; recategorised: number; failed: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const headingId = useId()

  const importPreview = useImportPreview()
  const confirmImport = useConfirmImport()
  const updateTransaction = useUpdateTransaction()

  const account = accounts?.find((a) => a.id === accountId)
  const step = result ? 2 : preview ? 1 : 0
  const ready = preview?.rows.filter((r) => r.is_parsable && !r.is_duplicate).length ?? 0
  const invalid = preview ? preview.total_rows - preview.parsable_rows : 0
  const skipFlagged = preview ? preview.rows.every((r) => (r.is_parsable && !r.is_duplicate) || !selectedRows.has(r.row_number)) : true

  async function handleUpload() {
    if (!accountId || !file) return
    setError(null)
    try {
      const next = await importPreview.mutateAsync({ accountId, file })
      setPreview(next)
      setCategoryEdits(new Map())
      // Pre-select every row that's parsable and not a likely duplicate —
      // the common case is "import everything new".
      setSelectedRows(new Set(next.rows.filter((r) => r.is_parsable && !r.is_duplicate).map((r) => r.row_number)))
    } catch (e) {
      setError(apiErrorMessage(e, 'Non è stato possibile leggere il file. Controlla il formato e riprova.'))
    }
  }

  function toggleRow(rowNumber: number) {
    setSelectedRows((prev) => {
      const next = new Set(prev)
      if (next.has(rowNumber)) next.delete(rowNumber)
      else next.add(rowNumber)
      return next
    })
  }

  function setSkipFlagged(skip: boolean) {
    if (!preview) return
    setSelectedRows(
      new Set(preview.rows.filter((r) => r.is_parsable && (skip ? !r.is_duplicate : true)).map((r) => r.row_number)),
    )
  }

  function categoryFor(row: TransactionImportRow): string {
    return categoryEdits.get(row.row_number) ?? row.suggested_category_id ?? ''
  }

  async function handleConfirm() {
    if (!preview) return
    setError(null)
    try {
      const created: Transaction[] = await confirmImport.mutateAsync({
        importId: preview.import_id,
        rowNumbers: Array.from(selectedRows),
      })
      const pool = new Map<string, Transaction[]>()
      for (const t of created) {
        const key = rowKey(t.date, t.amount, t.currency, t.description)
        pool.set(key, [...(pool.get(key) ?? []), t])
      }
      let recategorised = 0
      let failed = 0
      for (const row of preview.rows) {
        const edited = categoryEdits.get(row.row_number)
        if (!selectedRows.has(row.row_number) || edited === undefined || edited === (row.suggested_category_id ?? '')) continue
        const match = pool.get(rowKey(row.date, row.amount, row.currency, row.description))?.shift()
        if (!match) {
          failed += 1
          continue
        }
        try {
          await updateTransaction.mutateAsync({ id: match.id, payload: { category_id: edited || null } })
          recategorised += 1
        } catch {
          failed += 1
        }
      }
      setResult({ imported: created.length, recategorised, failed })
    } catch (e) {
      setError(apiErrorMessage(e, "Importazione non riuscita. L'anteprima scade dopo 15 minuti: ricarica il file e riprova."))
    }
  }

  return (
    <section aria-labelledby={headingId} className="rounded-[14px] border border-line bg-card px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={headingId} className="text-[16px] font-extrabold">
          Importa movimenti da CSV
        </h2>
        <Stepper step={step} />
      </div>

      {step === 0 && (
        <div className="mt-4 flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Conto di destinazione" htmlFor="import-account">
              <select id="import-account" value={accountId} onChange={(e) => setAccountId(e.target.value)} className="field">
                <option value="">Seleziona un conto</option>
                {accounts
                  ?.filter((a) => !a.deleted_at)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {a.currency}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="File CSV" htmlFor="import-file" hint="Colonne attese: date, amount, currency, description.">
              <input
                id="import-file"
                type="file"
                accept=".csv,text/csv"
                aria-describedby="import-file-msg"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="field py-2 file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-card-2 file:px-3 file:py-1.5 file:font-bold file:text-ink"
              />
            </Field>
          </div>
          {error && <ErrorBlock>{error}</ErrorBlock>}
          <div className="flex flex-wrap justify-end gap-2">
            <Button onClick={onDone}>Annulla</Button>
            <Button variant="primary" onClick={handleUpload} disabled={!accountId || !file || importPreview.isPending}>
              {importPreview.isPending ? 'Analisi in corso…' : 'Carica e analizza'}
            </Button>
          </div>
        </div>
      )}

      {step === 1 && preview && (
        <>
          <div className="mt-3.5 flex flex-wrap items-center gap-x-6 gap-y-3">
            <div className="flex flex-wrap items-center gap-2.5 rounded-[10px] bg-card-2 px-3 py-2 tabular-nums">
              <span>
                <b>{file?.name}</b> <span className="text-ink-3">→ {account?.name} · {account?.currency}</span>
              </span>
              <button type="button" onClick={() => setPreview(null)} className="link min-h-8 cursor-pointer text-[13px]">
                Cambia
              </button>
            </div>
            <div className="flex flex-wrap gap-2 text-[13px] font-bold tabular-nums">
              <span className="rounded-full bg-card-2 px-2.5 py-1">{preview.total_rows} righe</span>
              <span className="rounded-full bg-pos-soft px-2.5 py-1 text-pos">✓ {ready} pronte</span>
              {preview.duplicate_rows > 0 && (
                <span className="rounded-full bg-warn-soft px-2.5 py-1 text-warn">⧉ {preview.duplicate_rows} possibili duplicati</span>
              )}
              {invalid > 0 && <span className="rounded-full bg-neg-soft px-2.5 py-1 text-neg">✕ {invalid} non valide</span>}
            </div>
          </div>

          <div className="relative mt-3 overflow-x-auto rounded-[10px] border border-line">
            <table className="w-full min-w-[820px] border-collapse text-[13px] tabular-nums">
              <thead>
                <tr className="bg-card-2 text-left text-[12px] text-ink-3">
                  <th scope="col" className="w-10 px-3 py-2 font-bold">
                    <span className="sr-only">Importa</span>
                  </th>
                  <th scope="col" className="px-3 py-2 font-bold">#</th>
                  <th scope="col" className="px-3 py-2 font-bold">Data</th>
                  <th scope="col" className="px-3 py-2 font-bold">Descrizione</th>
                  <th scope="col" className="px-3 py-2 text-right font-bold">Importo</th>
                  <th scope="col" className="px-3 py-2 font-bold">Categoria proposta</th>
                  <th scope="col" className="px-3 py-2 font-bold">Stato</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => {
                  const type = Number(row.amount) < 0 ? 'expense' : 'income'
                  return (
                    <tr key={row.row_number} className={!row.is_parsable ? 'bg-neg-soft/40' : row.is_duplicate ? 'bg-warn-soft/40' : ''}>
                      <td className="border-t border-line px-3 py-1.5">
                        <input
                          type="checkbox"
                          aria-label={`Importa la riga ${row.row_number}`}
                          disabled={!row.is_parsable}
                          checked={selectedRows.has(row.row_number)}
                          onChange={() => toggleRow(row.row_number)}
                          className="h-[18px] w-[18px] cursor-pointer accent-accent"
                        />
                      </td>
                      <td className="border-t border-line px-3 py-2 text-ink-3">{row.row_number}</td>
                      <td className="border-t border-line px-3 py-2 whitespace-nowrap">{row.is_parsable ? formatShortDate(row.date) : '—'}</td>
                      <td className="border-t border-line px-3 py-2 font-semibold">
                        {row.description ?? '—'}
                        {row.error && <div className="text-[12px] font-bold text-neg">{row.error}</div>}
                      </td>
                      <td className="border-t border-line px-3 py-2 text-right font-bold whitespace-nowrap">
                        {row.is_parsable ? (
                          <>
                            {formatAmount(row.amount, row.currency, { sign: type === 'income' ? 'always' : 'auto' })} <span className="ccy">{row.currency}</span>
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="border-t border-line px-3 py-1.5">
                        {row.is_parsable && (
                          <CategorySelect
                            aria-label={`Categoria per la riga ${row.row_number}`}
                            categories={categories}
                            type={type}
                            emptyLabel="Varie (da assegnare)"
                            value={categoryFor(row)}
                            onChange={(e) => setCategoryEdits((prev) => new Map(prev).set(row.row_number, e.target.value))}
                            className="field min-h-10 text-[13px]"
                          />
                        )}
                      </td>
                      <td className="border-t border-line px-3 py-2">{rowStatus(row)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {error && (
            <div className="mt-3">
              <ErrorBlock>{error}</ErrorBlock>
            </div>
          )}

          <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3">
            <label className="flex min-h-11 cursor-pointer items-center gap-2 text-[14px]">
              <input
                type="checkbox"
                checked={skipFlagged}
                onChange={(e) => setSkipFlagged(e.target.checked)}
                className="h-[18px] w-[18px] accent-accent"
              />
              Salta i possibili duplicati e le righe non valide
            </label>
            <div className="flex flex-wrap gap-2">
              <Button onClick={onDone}>Annulla</Button>
              <Button variant="primary" onClick={handleConfirm} disabled={selectedRows.size === 0 || confirmImport.isPending || updateTransaction.isPending}>
                {confirmImport.isPending || updateTransaction.isPending
                  ? 'Importazione…'
                  : `Importa ${selectedRows.size} ${selectedRows.size === 1 ? 'movimento' : 'movimenti'}`}
              </Button>
            </div>
          </div>
        </>
      )}

      {step === 2 && result && (
        <div className="mt-4 flex flex-col gap-3">
          <p role="status" className="rounded-[10px] bg-pos-soft px-3 py-2 font-bold text-pos">
            ✓ {result.imported} {result.imported === 1 ? 'movimento importato' : 'movimenti importati'}
            {result.recategorised > 0 && ` · ${result.recategorised} con la categoria scelta da te`}
          </p>
          {result.imported < selectedRows.size && (
            <ErrorBlock>
              {selectedRows.size - result.imported} righe selezionate non sono state importate (cambio non disponibile per la data).
            </ErrorBlock>
          )}
          {result.failed > 0 && (
            <ErrorBlock>
              Per {result.failed} {result.failed === 1 ? 'movimento' : 'movimenti'} non è stato possibile applicare la categoria scelta: sono in
              Varie, puoi assegnarla dall'elenco.
            </ErrorBlock>
          )}
          <div className="flex justify-end">
            <Button variant="primary" onClick={onDone}>
              Fatto
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
