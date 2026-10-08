import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { useDeleteAssetTransaction, useUpdateAssetTransaction } from '@/hooks/useAssetTransactions'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatQuantity, formatShortDate } from '@/lib/format'
import { isLocaleNumber, parseLocaleNumber } from '@/lib/physicalAssets'
import type { AssetTransaction, AssetTransactionUpdatePayload } from '@/types'

/** "10.50000000" → "10.5": the API pads to the column's scale. */
function trimDecimal(value: string): string {
  return value.includes('.') ? value.replace(/0+$/, '').replace(/\.$/, '') : value
}

const verb = (tx: AssetTransaction) => (tx.type === 'buy' ? 'Acquisto' : 'Vendita')

export function EditAssetTransactionDialog({ transaction, onClose }: { transaction: AssetTransaction | null; onClose: () => void }) {
  return (
    <Dialog
      open={!!transaction}
      onClose={onClose}
      title={transaction ? `Modifica ${verb(transaction).toLowerCase()} ${transaction.asset.symbol}` : ''}
      description="Conto, titolo e tipo di operazione non si modificano: se sono sbagliati, elimina l'operazione e registrala di nuovo."
    >
      {transaction && <EditForm key={transaction.id} transaction={transaction} onClose={onClose} />}
    </Dialog>
  )
}

function EditForm({ transaction, onClose }: { transaction: AssetTransaction; onClose: () => void }) {
  const update = useUpdateAssetTransaction()
  const ccy = transaction.asset.currency
  const [quantity, setQuantity] = useState(() => trimDecimal(transaction.quantity))
  const [price, setPrice] = useState(() => trimDecimal(transaction.price))
  const [fee, setFee] = useState(() => trimDecimal(transaction.fee))
  const [date, setDate] = useState(transaction.date)
  const [notes, setNotes] = useState(transaction.notes ?? '')
  const [error, setError] = useState<string | null>(null)

  const valid =
    isLocaleNumber(quantity) && Number(parseLocaleNumber(quantity)) > 0 &&
    isLocaleNumber(price) && Number(parseLocaleNumber(price)) > 0 &&
    (fee.trim() === '' || (isLocaleNumber(fee) && Number(parseLocaleNumber(fee)) >= 0))
  const gross = valid ? Number(parseLocaleNumber(quantity)) * Number(parseLocaleNumber(price)) : null
  const feeValue = fee.trim() === '' ? 0 : Number(parseLocaleNumber(fee))
  const total = gross === null ? null : transaction.type === 'buy' ? gross + feeValue : gross - feeValue

  async function submit() {
    if (!valid || !date) {
      setError('Controlla quantità, prezzo, commissioni e data')
      return
    }
    // Only what changed: the backend re-converts at the day's rate whenever
    // quantity/price/fee/date appear, so a notes-only edit must not send them.
    const payload: AssetTransactionUpdatePayload = {}
    const numeric = (input: string) => trimDecimal(parseLocaleNumber(input.trim() === '' ? '0' : input))
    if (numeric(quantity) !== trimDecimal(transaction.quantity)) payload.quantity = numeric(quantity)
    if (numeric(price) !== trimDecimal(transaction.price)) payload.price = numeric(price)
    if (numeric(fee) !== trimDecimal(transaction.fee)) payload.fee = numeric(fee)
    if (date !== transaction.date) payload.date = date
    if ((notes.trim() || null) !== transaction.notes) payload.notes = notes.trim() || null
    if (Object.keys(payload).length === 0) {
      onClose()
      return
    }
    setError(null)
    try {
      await update.mutateAsync({ id: transaction.id, payload })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, "Impossibile salvare l'operazione."))
    }
  }

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Quantità" htmlFor="edit-tx-quantity">
          <input id="edit-tx-quantity" inputMode="decimal" className="field tabular-nums" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </Field>
        <Field label="Prezzo unitario" htmlFor="edit-tx-price">
          <div className="relative">
            <input id="edit-tx-price" inputMode="decimal" className="field pr-12 tabular-nums" value={price} onChange={(e) => setPrice(e.target.value)} />
            <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">{ccy}</span>
          </div>
        </Field>
        <Field label="Commissioni" htmlFor="edit-tx-fee">
          <div className="relative">
            <input id="edit-tx-fee" inputMode="decimal" placeholder="0" className="field pr-12 tabular-nums" value={fee} onChange={(e) => setFee(e.target.value)} />
            <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">{ccy}</span>
          </div>
        </Field>
        <Field label="Data" htmlFor="edit-tx-date">
          <input id="edit-tx-date" type="date" className="field" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
      </div>
      <Field label="Note (opzionale)" htmlFor="edit-tx-notes">
        <input id="edit-tx-notes" className="field" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      {total !== null && (
        <p className="text-[13px] text-ink-2 tabular-nums">
          {transaction.type === 'buy' ? 'Addebito' : 'Accredito'} sul conto: {formatAmount(total, ccy)} <span className="ccy">{ccy}</span> — il movimento di
          cassa collegato viene aggiornato.
        </p>
      )}
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" onClick={onClose}>
          Annulla
        </Button>
        <Button type="submit" variant="primary" disabled={update.isPending}>
          {update.isPending ? 'Salvataggio…' : 'Salva'}
        </Button>
      </div>
    </form>
  )
}

export function DeleteAssetTransactionDialog({ transaction, onClose }: { transaction: AssetTransaction | null; onClose: () => void }) {
  const deleteAssetTransaction = useDeleteAssetTransaction()
  const [error, setError] = useState<string | null>(null)

  function close() {
    setError(null)
    onClose()
  }

  async function confirm() {
    if (!transaction) return
    setError(null)
    try {
      await deleteAssetTransaction.mutateAsync(transaction.id)
      close()
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }

  return (
    <ConfirmDialog
      open={!!transaction}
      title="Eliminare questa operazione?"
      confirmLabel="Elimina"
      pending={deleteAssetTransaction.isPending}
      error={error}
      onConfirm={confirm}
      onCancel={close}
    >
      {transaction && (
        <>
          {verb(transaction)} di {formatQuantity(transaction.quantity)} {transaction.asset.symbol} del {formatShortDate(transaction.date)}. Posizione e
          liquidità del conto vengono ricalcolate.
        </>
      )}
    </ConfirmDialog>
  )
}
