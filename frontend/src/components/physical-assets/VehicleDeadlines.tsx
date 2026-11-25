import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { RowMenu, type RowMenuItem } from '@/components/ui/RowMenu'
import { StatusChip } from '@/components/ui/StatusChip'
import { useAccounts } from '@/hooks/useAccounts'
import {
  useCompleteVehicleDeadline,
  useCreateVehicleDeadline,
  useDeleteVehicleDeadline,
  useUpdateVehicleDeadline,
  useVehicleDeadlines,
} from '@/hooks/useVehicleDeadlines'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatFullDate, toISODate } from '@/lib/format'
import { isLocaleNumber, nextDeadlineDate, parseLocaleNumber, VEHICLE_DEADLINE_LABELS } from '@/lib/physicalAssets'
import type { PhysicalAssetWithValue, VehicleDeadline, VehicleDeadlineKind } from '@/types'

// Must match services/alerts.py: LEAD_DAYS.
const LEAD_DAYS = 14
const DAY_MS = 86_400_000

function daysUntil(iso: string, today: string): number {
  return Math.round((Date.parse(iso) - Date.parse(today)) / DAY_MS)
}

function deadlineName(d: VehicleDeadline): string {
  if (d.kind === 'other') return d.label ?? VEHICLE_DEADLINE_LABELS.other
  return d.label ? `${VEHICLE_DEADLINE_LABELS[d.kind]} (${d.label})` : VEHICLE_DEADLINE_LABELS[d.kind]
}

/**
 * Insurance, road tax, inspection, service for the vehicles still owned.
 * Reminders, not movements: "Fatto" records nothing on an account (the
 * expense is a normal transaction), it closes this one and can open the
 * next. One with an amount and an account counts against that account's
 * balance until it's done, and both feed the alerts at the top of the app.
 */
export function VehicleDeadlinesCard({ vehicles }: { vehicles: PhysicalAssetWithValue[] }) {
  const owned = vehicles.filter((v) => v.sold_at === null)
  const { data: deadlines } = useVehicleDeadlines()
  const { data: accounts } = useAccounts()
  const remove = useDeleteVehicleDeadline()
  const [editing, setEditing] = useState<{ deadline: VehicleDeadline | null } | null>(null)
  const [completing, setCompleting] = useState<VehicleDeadline | null>(null)
  const [deleting, setDeleting] = useState<VehicleDeadline | null>(null)
  const [error, setError] = useState<string | null>(null)
  const today = toISODate(new Date())

  if (owned.length === 0) return null
  const names = new Map(vehicles.map((v) => [v.id, v.name]))
  const accountName = (id: string) => (accounts ?? []).find((a) => a.id === id)?.name ?? 'conto'
  const rows = (deadlines ?? []).filter((d) => names.has(d.physical_asset_id))

  function actions(d: VehicleDeadline): RowMenuItem[] {
    return [
      { label: 'Fatto', onSelect: () => setCompleting(d) },
      { label: 'Modifica', onSelect: () => setEditing({ deadline: d }) },
      {
        label: 'Elimina',
        tone: 'danger',
        onSelect: () => {
          setError(null)
          setDeleting(d)
        },
      },
    ]
  }

  return (
    <Card
      title="Scadenze veicoli"
      action={
        <Button size="sm" onClick={() => setEditing({ deadline: null })}>
          + Scadenza
        </Button>
      }
    >
      {rows.length === 0 ? (
        <p className="mt-2 text-[13px] text-ink-3">
          Assicurazione, bollo, revisione, tagliando: segna le scadenze e ti avvisiamo due settimane prima. Con un importo e un conto, controlliamo anche che
          sul conto ci sia abbastanza.
        </p>
      ) : (
        <ul className="mt-2 text-[13px] tabular-nums">
          {rows.map((d) => {
            const days = daysUntil(d.due_date, today)
            return (
              <li key={d.id} className="flex items-center gap-2 border-t border-line py-2 first:border-t-0">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5 font-bold">
                    {names.get(d.physical_asset_id)} · {deadlineName(d)}
                    {days < 0 ? (
                      <StatusChip kind="over">scaduta</StatusChip>
                    ) : days <= LEAD_DAYS ? (
                      <StatusChip kind="warn">{days === 0 ? 'oggi' : days === 1 ? 'domani' : `tra ${days} giorni`}</StatusChip>
                    ) : null}
                  </div>
                  <div className="text-[12px] text-ink-3">
                    {formatFullDate(d.due_date)}
                    {d.account_id ? ` · da ${accountName(d.account_id)}` : ''}
                    {d.notes ? ` · ${d.notes}` : ''}
                  </div>
                </div>
                {d.amount && (
                  <span className="whitespace-nowrap">
                    {formatAmount(d.amount, d.currency)} <span className="ccy">{d.currency}</span>
                  </span>
                )}
                <RowMenu label={`Azioni per ${deadlineName(d)}`} items={actions(d)} />
              </li>
            )
          })}
        </ul>
      )}
      {error && deleting === null && <ErrorBlock>{error}</ErrorBlock>}

      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        size="md"
        title={editing?.deadline ? 'Modifica scadenza' : 'Nuova scadenza'}
        description="Ti avvisiamo due settimane prima. Con un importo e un conto, la cifra resta impegnata su quel conto finché non la segni come fatta."
      >
        {editing && <DeadlineForm key={editing.deadline?.id ?? 'new'} deadline={editing.deadline} vehicles={owned} onClose={() => setEditing(null)} />}
      </Dialog>
      <Dialog open={completing !== null} onClose={() => setCompleting(null)} size="sm" title={completing ? `Fatto: ${deadlineName(completing)}` : ''}>
        {completing && <CompleteForm key={completing.id} deadline={completing} onClose={() => setCompleting(null)} />}
      </Dialog>
      <ConfirmDialog
        open={deleting !== null}
        title={deleting ? `Eliminare «${deadlineName(deleting)}»?` : ''}
        confirmLabel="Elimina"
        onConfirm={async () => {
          if (!deleting) return
          try {
            await remove.mutateAsync(deleting.id)
            setDeleting(null)
          } catch (e) {
            setError(apiErrorMessage(e, 'Impossibile eliminare la scadenza.'))
          }
        }}
        onCancel={() => setDeleting(null)}
        pending={remove.isPending}
        error={error}
      >
        Se l&apos;hai già fatta, usa «Fatto»: puoi anche creare la prossima.
      </ConfirmDialog>
    </Card>
  )
}

function DeadlineForm({ deadline, vehicles, onClose }: { deadline: VehicleDeadline | null; vehicles: PhysicalAssetWithValue[]; onClose: () => void }) {
  const create = useCreateVehicleDeadline()
  const update = useUpdateVehicleDeadline()
  const { data: accounts } = useAccounts()
  const [vehicleId, setVehicleId] = useState(deadline?.physical_asset_id ?? vehicles[0]?.id ?? '')
  const [kind, setKind] = useState<VehicleDeadlineKind>(deadline?.kind ?? 'insurance')
  const [label, setLabel] = useState(deadline?.label ?? '')
  const [dueDate, setDueDate] = useState(deadline?.due_date ?? toISODate(new Date()))
  const [amount, setAmount] = useState(deadline?.amount ? deadline.amount.replace('.', ',') : '')
  const [accountId, setAccountId] = useState(deadline?.account_id ?? '')
  const [notes, setNotes] = useState(deadline?.notes ?? '')
  const [error, setError] = useState<string | null>(null)
  const open = (accounts ?? []).filter((a) => !a.deleted_at && !a.closed_at)
  const currency = open.find((a) => a.id === accountId)?.currency ?? vehicles.find((v) => v.id === vehicleId)?.currency ?? 'EUR'

  async function submit() {
    if (!vehicleId) return setError('Scegli il veicolo')
    if (kind === 'other' && !label.trim()) return setError('Dai un nome alla scadenza')
    if (amount.trim() && (!isLocaleNumber(amount) || Number(parseLocaleNumber(amount)) <= 0)) return setError('Inserisci un importo valido')
    if (accountId && !amount.trim()) return setError("Con un conto serve l'importo: è quello che controlliamo sul saldo")
    setError(null)
    const payload = {
      kind,
      label: label.trim() || null,
      due_date: dueDate,
      amount: amount.trim() ? parseLocaleNumber(amount) : null,
      account_id: accountId || null,
      notes: notes.trim() || null,
    }
    try {
      if (deadline) await update.mutateAsync({ id: deadline.id, payload })
      else await create.mutateAsync({ ...payload, physical_asset_id: vehicleId })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare la scadenza.'))
    }
  }

  const pending = create.isPending || update.isPending
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-2.5 sm:grid-cols-2">
        <Field label="Veicolo" htmlFor="dl-vehicle">
          <select id="dl-vehicle" className="field" value={vehicleId} disabled={!!deadline} onChange={(e) => setVehicleId(e.target.value)}>
            {vehicles.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Tipo" htmlFor="dl-kind">
          <select id="dl-kind" className="field" value={kind} onChange={(e) => setKind(e.target.value as VehicleDeadlineKind)}>
            {(Object.keys(VEHICLE_DEADLINE_LABELS) as VehicleDeadlineKind[]).map((k) => (
              <option key={k} value={k}>
                {VEHICLE_DEADLINE_LABELS[k]}
              </option>
            ))}
          </select>
        </Field>
        <Field label={kind === 'other' ? 'Nome' : 'Dettaglio'} htmlFor="dl-label" hint={kind === 'other' ? undefined : 'Facoltativo, es. «Kasko».'}>
          <input id="dl-label" className="field" value={label} maxLength={100} onChange={(e) => setLabel(e.target.value)} />
        </Field>
        <Field label="Scadenza" htmlFor="dl-date">
          <input id="dl-date" type="date" className="field" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
        </Field>
        <Field label="Importo" htmlFor="dl-amount" hint="Facoltativo.">
          <div className="relative">
            <input id="dl-amount" inputMode="decimal" placeholder="0,00" className="field pr-12 tabular-nums" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">{currency}</span>
          </div>
        </Field>
        <Field label="Pagata da" htmlFor="dl-account" hint="Facoltativo: controlliamo che sul conto ci sia l'importo.">
          <select id="dl-account" className="field" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Nessun conto</option>
            {open.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {a.currency}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="Note" htmlFor="dl-notes">
        <input id="dl-notes" className="field" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={submit} disabled={pending}>
          {pending ? 'Attendi…' : deadline ? 'Salva' : 'Aggiungi'}
        </Button>
      </div>
    </div>
  )
}

function CompleteForm({ deadline, onClose }: { deadline: VehicleDeadline; onClose: () => void }) {
  const complete = useCompleteVehicleDeadline()
  const [doneOn, setDoneOn] = useState(toISODate(new Date()))
  const [repeat, setRepeat] = useState(true)
  const [nextDate, setNextDate] = useState(nextDeadlineDate(deadline.kind, deadline.due_date))
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (repeat && nextDate <= deadline.due_date) return setError('La prossima scadenza deve venire dopo questa')
    setError(null)
    try {
      await complete.mutateAsync({ id: deadline.id, payload: { done_on: doneOn, next_due_date: repeat ? nextDate : null } })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile segnare la scadenza come fatta.'))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-ink-2">Non registra nessuna uscita: la spesa la inserisci come una normale transazione, o arriva con l&apos;estratto conto.</p>
      <Field label="Fatta il" htmlFor="dl-done">
        <input id="dl-done" type="date" className="field" value={doneOn} onChange={(e) => setDoneOn(e.target.value)} />
      </Field>
      <label className="flex min-h-11 w-fit cursor-pointer items-center gap-2 text-[14px] font-semibold">
        <input type="checkbox" className="h-4 w-4" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} />
        Crea la prossima scadenza
      </label>
      {repeat && (
        <Field label="Prossima scadenza" htmlFor="dl-next" hint="Stesso tipo, importo e conto.">
          <input id="dl-next" type="date" className="field" value={nextDate} onChange={(e) => setNextDate(e.target.value)} />
        </Field>
      )}
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Annulla</Button>
        <Button variant="primary" onClick={submit} disabled={complete.isPending}>
          {complete.isPending ? 'Attendi…' : 'Segna come fatta'}
        </Button>
      </div>
    </div>
  )
}
