import { useState } from 'react'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import {
  useCreateMovement,
  useCreateValuation,
  useDeleteMovement,
  useDeleteValuation,
  useSellPhysicalAsset,
} from '@/hooks/usePhysicalAssets'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatFullDate, formatQuantity, toISODate, toNumber } from '@/lib/format'
import { isLocaleNumber, parseLocaleNumber } from '@/lib/physicalAssets'
import type { MetalMovementType, PhysicalAssetWithValue } from '@/types'

export function SellDialog({ asset, onClose }: { asset: PhysicalAssetWithValue | null; onClose: () => void }) {
  return (
    <Dialog
      open={!!asset}
      onClose={onClose}
      title={asset ? `Vendi ${asset.name}` : ''}
      description="Il bene esce dal patrimonio dalla data di vendita. Puoi annullare la vendita in seguito."
    >
      {asset && <SellForm key={asset.id} asset={asset} onClose={onClose} />}
    </Dialog>
  )
}

function SellForm({ asset, onClose }: { asset: PhysicalAssetWithValue; onClose: () => void }) {
  const sell = useSellPhysicalAsset()
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const [soldAt, setSoldAt] = useState(() => toISODate(new Date()))
  const [price, setPrice] = useState('')
  const [accountId, setAccountId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const receiving = (accounts ?? []).filter((a) => a.currency === asset.currency && !a.closed_at)

  async function submit() {
    if (!isLocaleNumber(price) || Number(parseLocaleNumber(price)) < 0) {
      setError('Inserisci un prezzo di vendita valido')
      return
    }
    setError(null)
    try {
      await sell.mutateAsync({
        id: asset.id,
        payload: {
          sold_at: soldAt,
          sale_price: parseLocaleNumber(price),
          account_id: accountId || null,
          category_id: accountId && categoryId ? categoryId : null,
        },
      })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile registrare la vendita.'))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Data di vendita" htmlFor="sell-date">
          <input id="sell-date" type="date" className="field" value={soldAt} onChange={(e) => setSoldAt(e.target.value)} />
        </Field>
        <Field label="Prezzo" htmlFor="sell-price">
          <div className="relative">
            <input id="sell-price" inputMode="decimal" placeholder="0,00" className="field pr-12 tabular-nums" value={price} onChange={(e) => setPrice(e.target.value)} />
            <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">{asset.currency}</span>
          </div>
        </Field>
      </div>
      <Field label="Incassato su" htmlFor="sell-account" hint="Facoltativo: registra l'entrata come giroconto sul conto scelto.">
        <select id="sell-account" className="field" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Nessun conto</option>
          {receiving.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </Field>
      {accountId && (
        <Field label="Categoria del giroconto" htmlFor="sell-category">
          <CategorySelect id="sell-category" categories={categories} type="transfer" emptyLabel="Nessuna categoria" value={categoryId} onChange={(e) => setCategoryId(e.target.value)} />
        </Field>
      )}
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={submit} disabled={sell.isPending}>
          {sell.isPending ? 'Attendi…' : 'Registra vendita'}
        </Button>
      </div>
    </div>
  )
}

export function ValuationsDialog({ asset, onClose }: { asset: PhysicalAssetWithValue | null; onClose: () => void }) {
  return (
    <Dialog
      open={!!asset}
      onClose={onClose}
      size="md"
      title={asset ? `Valutazioni · ${asset.name}` : ''}
      description="Una quotazione (concessionario, annuncio, perizia) diventa il nuovo punto di partenza: da quella data la svalutazione riparte dal valore indicato."
    >
      {asset && <ValuationsPanel key={asset.id} asset={asset} />}
    </Dialog>
  )
}

function ValuationsPanel({ asset }: { asset: PhysicalAssetWithValue }) {
  const create = useCreateValuation()
  const remove = useDeleteValuation()
  // The dialog keeps the asset it was opened with; mirror the server's
  // answer so the list reflects each add/delete without reopening.
  const [current, setCurrent] = useState(asset)
  const [date, setDate] = useState(() => toISODate(new Date()))
  const [value, setValue] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function add() {
    if (!isLocaleNumber(value) || Number(parseLocaleNumber(value)) < 0) {
      setError('Inserisci un valore valido')
      return
    }
    setError(null)
    try {
      setCurrent(await create.mutateAsync({ id: asset.id, payload: { date, value: parseLocaleNumber(value), notes: notes.trim() || null } }))
      setValue('')
      setNotes('')
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare la valutazione.'))
    }
  }

  async function del(valuationId: string) {
    setError(null)
    try {
      setCurrent(await remove.mutateAsync({ id: asset.id, valuationId }))
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }

  const rows = [...current.valuations].reverse()
  return (
    <div className="flex flex-col gap-4">
      <ul className="tabular-nums">
        {rows.map((v) => (
          <li key={v.id} className="flex items-center gap-3 border-b border-line py-2">
            <div className="min-w-0 flex-1">
              <div className="font-bold">
                {formatAmount(v.value, current.currency)} <span className="ccy">{current.currency}</span>
              </div>
              <div className="truncate text-[12px] text-ink-3">
                {formatFullDate(v.date)}
                {v.notes ? ` · ${v.notes}` : ''}
              </div>
            </div>
            <Button size="sm" onClick={() => del(v.id)} disabled={remove.isPending} aria-label={`Elimina la valutazione del ${formatFullDate(v.date)}`}>
              Elimina
            </Button>
          </li>
        ))}
        <li className="flex items-center gap-3 py-2 text-ink-3">
          <div className="min-w-0 flex-1">
            <div className="font-bold">
              {formatAmount(current.purchase_price, current.currency)} <span className="ccy">{current.currency}</span>
            </div>
            <div className="text-[12px]">{formatFullDate(current.purchase_date)} · acquisto</div>
          </div>
        </li>
      </ul>

      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Data" htmlFor="val-date">
          <input id="val-date" type="date" className="field" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Valore" htmlFor="val-value">
          <div className="relative">
            <input id="val-value" inputMode="decimal" placeholder="0,00" className="field pr-12 tabular-nums" value={value} onChange={(e) => setValue(e.target.value)} />
            <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">{current.currency}</span>
          </div>
        </Field>
      </div>
      <Field label="Fonte (facoltativa)" htmlFor="val-notes">
        <input id="val-notes" className="field" placeholder="Es. quotazione concessionario" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end">
        <Button variant="primary" onClick={add} disabled={create.isPending}>
          {create.isPending ? 'Attendi…' : 'Aggiungi valutazione'}
        </Button>
      </div>
    </div>
  )
}

export function MovementsDialog({
  asset,
  initialType,
  onClose,
}: {
  asset: PhysicalAssetWithValue | null
  initialType: MetalMovementType
  onClose: () => void
}) {
  return (
    <Dialog
      open={!!asset}
      onClose={onClose}
      size="md"
      title={asset ? `Acquista o vendi · ${asset.name}` : ''}
      description="Il metallo si compra e si vende a grammi: il costo dei grammi rimasti è la media ponderata degli acquisti."
    >
      {asset && <MovementsPanel key={asset.id} asset={asset} initialType={initialType} />}
    </Dialog>
  )
}

function MovementsPanel({ asset, initialType }: { asset: PhysicalAssetWithValue; initialType: MetalMovementType }) {
  const create = useCreateMovement()
  const remove = useDeleteMovement()
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  // Mirror the server's answer so the list and the grams held update in
  // place after each add/delete, without reopening the dialog.
  const [current, setCurrent] = useState(asset)
  const [type, setType] = useState<MetalMovementType>(initialType)
  const held = toNumber(current.weight_grams)
  const [date, setDate] = useState(() => toISODate(new Date()))
  // A sale defaults to everything held: selling the lot is the common case.
  const [grams, setGrams] = useState(() => (initialType === 'sell' && held > 0 ? String(held).replace('.', ',') : ''))
  const [price, setPrice] = useState('')
  const [accountId, setAccountId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const sameCurrency = (accounts ?? []).filter((a) => a.currency === current.currency && !a.closed_at)
  const accountName = new Map((accounts ?? []).map((a) => [a.id, a.name]))

  async function add() {
    if (!isLocaleNumber(grams) || Number(parseLocaleNumber(grams)) <= 0) {
      setError('Inserisci un peso maggiore di zero')
      return
    }
    if (price && !(isLocaleNumber(price) && Number(parseLocaleNumber(price)) >= 0)) {
      setError('Inserisci un importo valido')
      return
    }
    if (!price && (type === 'sell' || accountId)) {
      setError(type === 'sell' ? 'Una vendita ha sempre un prezzo' : 'Serve un prezzo per pagarlo da un conto')
      return
    }
    setError(null)
    try {
      setCurrent(
        await create.mutateAsync({
          id: asset.id,
          payload: {
            type,
            date,
            weight_grams: parseLocaleNumber(grams),
            price: price ? parseLocaleNumber(price) : null,
            account_id: accountId || null,
            category_id: accountId && categoryId ? categoryId : null,
            notes: notes.trim() || null,
          },
        }),
      )
      setGrams('')
      setPrice('')
      setNotes('')
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile registrare il movimento.'))
    }
  }

  async function del(movementId: string) {
    setError(null)
    try {
      setCurrent(await remove.mutateAsync({ id: asset.id, movementId }))
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }

  const rows = [...current.movements].reverse()
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[14px] font-bold tabular-nums">
        Posseduti: {formatQuantity(current.weight_grams ?? 0)} g
      </p>
      <ul className="tabular-nums">
        {rows.map((m) => (
          <li key={m.id} className="flex items-center gap-3 border-b border-line py-2 last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="font-bold">
                {m.type === 'buy' ? 'Acquisto' : 'Vendita'} {formatQuantity(m.weight_grams)} g
                {m.price !== null && (
                  <span className="font-semibold text-ink-2">
                    {' '}· {formatAmount(m.price, current.currency)} <span className="ccy">{current.currency}</span>
                  </span>
                )}
              </div>
              <div className="truncate text-[12px] text-ink-3">
                {formatFullDate(m.date)}
                {m.account_id ? ` · ${m.type === 'buy' ? 'da' : 'su'} ${accountName.get(m.account_id) ?? 'conto'}` : ''}
                {m.price === null ? ' · senza costo' : ''}
                {m.notes ? ` · ${m.notes}` : ''}
              </div>
            </div>
            <Button
              size="sm"
              onClick={() => del(m.id)}
              disabled={remove.isPending || rows.length === 1}
              title={rows.length === 1 ? 'Unico movimento: elimina il bene invece' : undefined}
              aria-label={`Elimina il movimento del ${formatFullDate(m.date)}`}
            >
              Elimina
            </Button>
          </li>
        ))}
      </ul>

      <SegmentedControl
        label="Tipo di movimento"
        options={[
          { value: 'buy', label: 'Acquisto' },
          { value: 'sell', label: 'Vendita' },
        ]}
        value={type}
        onChange={setType}
      />
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Data" htmlFor="mov-date">
          <input id="mov-date" type="date" className="field" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Peso" htmlFor="mov-grams" hint={type === 'sell' ? `Massimo ${formatQuantity(held)} g oggi` : undefined}>
          <div className="relative">
            <input id="mov-grams" inputMode="decimal" placeholder="0,00" className="field pr-8 tabular-nums" value={grams} onChange={(e) => setGrams(e.target.value)} />
            <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">g</span>
          </div>
        </Field>
      </div>
      <Field
        label={type === 'sell' ? 'Incasso totale' : 'Prezzo totale (facoltativo)'}
        htmlFor="mov-price"
        hint={type === 'buy' ? 'Vuoto per un regalo o un\'eredità: quei grammi restano senza costo.' : undefined}
      >
        <div className="relative">
          <input id="mov-price" inputMode="decimal" placeholder="0,00" className="field pr-12 tabular-nums" value={price} onChange={(e) => setPrice(e.target.value)} />
          <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">{current.currency}</span>
        </div>
      </Field>
      <Field
        label={type === 'sell' ? 'Incassato su' : 'Pagato da'}
        htmlFor="mov-account"
        hint="Facoltativo: registra il movimento di cassa come giroconto."
      >
        <select id="mov-account" className="field" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Nessun conto</option>
          {sameCurrency.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </Field>
      {accountId && (
        <Field label="Categoria del giroconto" htmlFor="mov-category">
          <CategorySelect id="mov-category" categories={categories} type="transfer" emptyLabel="Nessuna categoria" value={categoryId} onChange={(e) => setCategoryId(e.target.value)} />
        </Field>
      )}
      <Field label="Note (facoltative)" htmlFor="mov-notes">
        <input id="mov-notes" className="field" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end">
        <Button variant="primary" onClick={add} disabled={create.isPending}>
          {create.isPending ? 'Attendi…' : type === 'sell' ? 'Registra vendita' : 'Registra acquisto'}
        </Button>
      </div>
    </div>
  )
}
