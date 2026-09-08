import { useState } from 'react'
import { useAccounts } from '@/hooks/useAccounts'
import { useConfirmImport, useImportPreview } from '@/hooks/useTransactions'
import type { TransactionImportPreview } from '@/types'

export function ImportPage() {
  const { data: accounts } = useAccounts()
  const [accountId, setAccountId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<TransactionImportPreview | null>(null)
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set())
  const [confirmedCount, setConfirmedCount] = useState<number | null>(null)

  const importPreview = useImportPreview()
  const confirmImport = useConfirmImport()

  async function handleUpload() {
    if (!accountId || !file) return
    setConfirmedCount(null)
    const result = await importPreview.mutateAsync({ accountId, file })
    setPreview(result)
    // Pre-select every row that's parsable and not a likely duplicate —
    // the common case is "import everything new", so this saves clicking
    // through rows that are almost always meant to be included.
    const defaultSelected = new Set(
      result.rows.filter((r) => r.is_parsable && !r.is_duplicate).map((r) => r.row_number),
    )
    setSelectedRows(defaultSelected)
  }

  function toggleRow(rowNumber: number) {
    setSelectedRows((prev) => {
      const next = new Set(prev)
      if (next.has(rowNumber)) {
        next.delete(rowNumber)
      } else {
        next.add(rowNumber)
      }
      return next
    })
  }

  async function handleConfirm() {
    if (!preview) return
    const created = await confirmImport.mutateAsync({
      importId: preview.import_id,
      rowNumbers: Array.from(selectedRows),
    })
    setConfirmedCount(created.length)
    setPreview(null)
    setFile(null)
    setSelectedRows(new Set())
  }

  function handleReset() {
    setPreview(null)
    setFile(null)
    setSelectedRows(new Set())
    setConfirmedCount(null)
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-800">Importa CSV</h1>

      {confirmedCount !== null && (
        <div className="rounded-lg bg-green-50 p-4 text-sm text-green-800">
          {confirmedCount} transazioni importate con successo.
        </div>
      )}

      {!preview && (
        <div className="space-y-4 rounded-lg bg-white p-6 shadow-sm">
          <div>
            <label htmlFor="import-account" className="block text-sm font-medium text-slate-700">
              Conto di destinazione
            </label>
            <select
              id="import-account"
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              className="mt-1 w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="">Seleziona un conto</option>
              {accounts?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.currency})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="import-file" className="block text-sm font-medium text-slate-700">
              File CSV
            </label>
            <p className="mb-1 text-xs text-slate-400">Colonne attese: date, amount, currency, description</p>
            <input
              id="import-file"
              type="file"
              accept=".csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 block text-sm text-slate-600"
            />
          </div>

          {importPreview.isError && (
            <p className="text-sm text-red-600">Errore durante la lettura del file. Riprova.</p>
          )}

          <button
            onClick={handleUpload}
            disabled={!accountId || !file || importPreview.isPending}
            className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {importPreview.isPending ? 'Analisi in corso...' : 'Carica e analizza'}
          </button>
        </div>
      )}

      {preview && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-4 rounded-lg bg-white p-4 text-sm shadow-sm">
            <span className="text-slate-600">
              <strong>{preview.total_rows}</strong> righe totali
            </span>
            <span className="text-green-700">
              <strong>{preview.parsable_rows}</strong> valide
            </span>
            <span className="text-amber-700">
              <strong>{preview.duplicate_rows}</strong> possibili duplicati
            </span>
            <span className="text-slate-600">
              <strong>{selectedRows.size}</strong> selezionate per l'import
            </span>
          </div>

          <div className="overflow-x-auto rounded-lg bg-white shadow-sm">
            <table className="min-w-full divide-y divide-slate-100 text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase text-slate-400">
                  <th className="px-4 py-3"></th>
                  <th className="px-4 py-3">Data</th>
                  <th className="px-4 py-3">Importo</th>
                  <th className="px-4 py-3">Valuta</th>
                  <th className="px-4 py-3">Descrizione</th>
                  <th className="px-4 py-3">Stato</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {preview.rows.map((row) => (
                  <tr key={row.row_number} className={row.is_parsable ? '' : 'bg-red-50'}>
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        disabled={!row.is_parsable}
                        checked={selectedRows.has(row.row_number)}
                        onChange={() => toggleRow(row.row_number)}
                      />
                    </td>
                    <td className="px-4 py-3">{row.is_parsable ? row.date : '—'}</td>
                    <td className="px-4 py-3">{row.is_parsable ? row.amount : '—'}</td>
                    <td className="px-4 py-3">{row.is_parsable ? row.currency : '—'}</td>
                    <td className="px-4 py-3">{row.description ?? '—'}</td>
                    <td className="px-4 py-3">
                      {!row.is_parsable && (
                        <span className="text-xs font-medium text-red-600">Riga non valida</span>
                      )}
                      {row.is_parsable && row.is_duplicate && (
                        <span className="text-xs font-medium text-amber-600">Possibile duplicato</span>
                      )}
                      {row.is_parsable && !row.is_duplicate && (
                        <span className="text-xs font-medium text-green-600">OK</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex gap-3">
            <button
              onClick={handleConfirm}
              disabled={selectedRows.size === 0 || confirmImport.isPending}
              className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {confirmImport.isPending
                ? 'Importazione...'
                : `Importa ${selectedRows.size} transazioni`}
            </button>
            <button
              onClick={handleReset}
              className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
            >
              Annulla
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
