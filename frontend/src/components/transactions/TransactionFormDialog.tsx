import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import { useCreateTransaction, useCreateTransfer, useUpdateTransaction } from '@/hooks/useTransactions'
import { apiErrorMessage } from '@/lib/apiError'
import { NECESSITY_LABELS } from '@/lib/categories'
import { toISODate } from '@/lib/format'
import type { NecessityLevel, Transaction, TransactionType } from '@/types'

const TYPE_OPTIONS: { value: TransactionType; label: string }[] = [
  { value: 'expense', label: 'Uscita' },
  { value: 'income', label: 'Entrata' },
  { value: 'transfer', label: 'Trasferimento' },
]

const baseSchema = z.object({
  type: z.enum(['expense', 'income', 'transfer']),
  account_id: z.string().min(1, 'Seleziona un conto'),
  // New transfers only: the giroconto's other side. An existing leg can't
  // change accounts, so edit mode never asks for it.
  to_account_id: z.string().optional(),
  category_id: z.string().optional(),
  amount: z
    .string()
    .min(1, 'Importo obbligatorio')
    .refine((v) => Number.isFinite(Number(v.replace(',', '.'))) && Number(v.replace(',', '.')) > 0, 'Inserisci un importo maggiore di zero'),
  currency: z.string().length(3, 'Codice valuta di 3 lettere'),
  date: z.string().min(1, 'Data obbligatoria'),
  description: z.string().optional(),
  // Expense only — the backend 422s an override on income/transfer, since a
  // necessity level has no meaning there.
  necessity_level_override: z.enum(['primary', 'useful', 'discretionary']).or(z.literal('')).optional(),
})

type FormValues = z.infer<typeof baseSchema>

function makeSchema(editing: boolean) {
  return baseSchema.superRefine((values, ctx) => {
    if (editing || values.type !== 'transfer') return
    if (!values.to_account_id) {
      ctx.addIssue({ code: 'custom', path: ['to_account_id'], message: 'Seleziona il conto di destinazione' })
    } else if (values.to_account_id === values.account_id) {
      ctx.addIssue({ code: 'custom', path: ['to_account_id'], message: 'Scegli un conto diverso da quello di partenza' })
    }
  })
}

interface Props {
  open: boolean
  onClose: () => void
  // Edit mode when given. Account, type and currency are fixed after
  // creation (the backend's update schema doesn't accept them).
  transaction?: Transaction | null
}

function initialValues(transaction?: Transaction | null): FormValues {
  if (transaction) {
    return {
      type: transaction.type,
      account_id: transaction.account_id,
      to_account_id: '',
      category_id: transaction.category_id ?? '',
      amount: String(Math.abs(Number(transaction.amount))),
      currency: transaction.currency,
      date: transaction.date,
      description: transaction.description ?? '',
      necessity_level_override: transaction.necessity_level_override ?? '',
    }
  }
  return { type: 'expense', account_id: '', to_account_id: '', category_id: '', amount: '', currency: '', date: toISODate(new Date()), description: '', necessity_level_override: '' }
}

function TransactionForm({ transaction, onDone }: { transaction?: Transaction | null; onDone: () => void }) {
  const editing = !!transaction
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const createTransaction = useCreateTransaction()
  const createTransfer = useCreateTransfer()
  const updateTransaction = useUpdateTransaction()
  const [serverError, setServerError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    control,
    setValue,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(makeSchema(editing)), defaultValues: initialValues(transaction) })

  const type = useWatch({ control, name: 'type' })
  const fromAccountId = useWatch({ control, name: 'account_id' })
  // Closed accounts refuse new movements dated after the close; a back-dated
  // fix is rare enough that reopening the account first is the way in.
  const activeAccounts = (accounts ?? []).filter((a) => !a.deleted_at && !a.closed_at)
  const isNewTransfer = !editing && type === 'transfer'
  // Giroconti are same-currency only (the backend 422s otherwise), so only
  // offer destinations that can actually receive the money.
  const fromAccount = activeAccounts.find((a) => a.id === fromAccountId)
  const destinationAccounts = activeAccounts.filter((a) => a.id !== fromAccountId && (!fromAccount || a.currency === fromAccount.currency))

  async function onSubmit(values: FormValues) {
    setServerError(null)
    // The form takes a positive number; the sign follows the type (expenses
    // negative), so nobody has to type a minus.
    const magnitude = Math.abs(Number(values.amount.replace(',', '.')))
    // An existing transfer keeps its own sign: the outgoing leg of a
    // giroconto (or a portfolio buy) is negative, and flipping it would read
    // as an amount edit — a 409 on a linked leg.
    const negative = transaction?.type === 'transfer' ? Number(transaction.amount) < 0 : values.type === 'expense'
    const amount = negative ? `-${magnitude}` : String(magnitude)
    const override = values.type === 'expense' && values.necessity_level_override ? values.necessity_level_override : null
    try {
      if (transaction) {
        await updateTransaction.mutateAsync({
          id: transaction.id,
          payload: {
            category_id: values.category_id || null,
            // Only send what changed: touching amount/date recomputes the frozen
            // rate, and on a paired giroconto leg it's a 409.
            ...(Number(transaction.amount) !== Number(amount) ? { amount } : {}),
            ...(transaction.date !== values.date ? { date: values.date } : {}),
            description: values.description || null,
            necessity_level_override: override,
          },
        })
      } else if (values.type === 'transfer') {
        await createTransfer.mutateAsync({
          from_account_id: values.account_id,
          to_account_id: values.to_account_id ?? '',
          category_id: values.category_id || null,
          amount: String(magnitude),
          date: values.date,
          description: values.description || null,
        })
      } else {
        await createTransaction.mutateAsync({
          account_id: values.account_id,
          category_id: values.category_id || null,
          amount,
          currency: values.currency.toUpperCase(),
          date: values.date,
          description: values.description || null,
          type: values.type,
          necessity_level_override: override,
        })
      }
      onDone()
    } catch (error) {
      setServerError(apiErrorMessage(error))
    }
  }

  const accountField = register('account_id')

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
      {!editing && (
        <SegmentedControl
          label="Tipo di movimento"
          options={TYPE_OPTIONS}
          value={type}
          onChange={(next) => {
            setValue('type', next)
            setValue('category_id', '')
          }}
          className="self-start"
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={isNewTransfer ? 'Da conto' : 'Conto'} htmlFor="tx-account" error={errors.account_id?.message}>
          <select
            id="tx-account"
            disabled={editing}
            aria-invalid={!!errors.account_id}
            aria-describedby={errors.account_id ? 'tx-account-msg' : undefined}
            className="field"
            {...accountField}
            onChange={(event) => {
              accountField.onChange(event)
              // Default the currency to the account's own; still editable.
              const account = activeAccounts.find((a) => a.id === event.target.value)
              if (account) setValue('currency', account.currency)
              // Drop a destination that no longer fits the new source.
              const destination = activeAccounts.find((a) => a.id === getValues('to_account_id'))
              if (destination && (destination.id === account?.id || destination.currency !== account?.currency)) setValue('to_account_id', '')
            }}
          >
            <option value="">Seleziona un conto</option>
            {(editing ? accounts ?? [] : activeAccounts).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {a.currency}
              </option>
            ))}
          </select>
        </Field>

        {isNewTransfer && (
          <Field label="A conto" htmlFor="tx-to-account" error={errors.to_account_id?.message} hint={fromAccount ? `Solo conti in ${fromAccount.currency}.` : undefined}>
            <select
              id="tx-to-account"
              aria-invalid={!!errors.to_account_id}
              aria-describedby="tx-to-account-msg"
              className="field"
              {...register('to_account_id')}
            >
              <option value="">Seleziona un conto</option>
              {destinationAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} · {a.currency}
                </option>
              ))}
            </select>
          </Field>
        )}

        <Field label="Data" htmlFor="tx-date" error={errors.date?.message}>
          <input id="tx-date" type="date" className="field" aria-invalid={!!errors.date} {...register('date')} />
        </Field>

        <Field label="Importo" htmlFor="tx-amount" error={errors.amount?.message} hint={type === 'expense' ? 'Scrivi un numero positivo: il segno − lo mette il tipo.' : undefined}>
          <input
            id="tx-amount"
            inputMode="decimal"
            placeholder="0,00"
            aria-invalid={!!errors.amount}
            aria-describedby="tx-amount-msg"
            className="field tabular-nums"
            {...register('amount')}
          />
        </Field>

        <Field label="Valuta" htmlFor="tx-currency" error={errors.currency?.message}>
          <input id="tx-currency" maxLength={3} disabled={editing} readOnly={isNewTransfer} aria-invalid={!!errors.currency} className="field uppercase" {...register('currency')} />
        </Field>

        {/* Optional on a transfer, and no "Varie" fallback: it only organises
            giroconti, it never counts as spend. */}
        <Field label="Categoria" htmlFor="tx-category" hint={type === 'transfer' ? 'Facoltativa: resta fuori da totali e piano.' : 'Se la lasci vuota finisce in “Varie”.'}>
          <CategorySelect
            id="tx-category"
            aria-describedby="tx-category-msg"
            categories={categories}
            type={type}
            emptyLabel={type === 'transfer' ? 'Nessuna' : 'Nessuna (Varie)'}
            {...register('category_id')}
          />
        </Field>

        {type === 'expense' && (
          <Field label="Livello di necessità" htmlFor="tx-necessity" hint="Solo per le eccezioni, es. una cena di lavoro sotto “Ristoranti”.">
            <select id="tx-necessity" aria-describedby="tx-necessity-msg" className="field" {...register('necessity_level_override')}>
              <option value="">Eredita dalla categoria</option>
              {(Object.keys(NECESSITY_LABELS) as NecessityLevel[]).map((level) => (
                <option key={level} value={level}>
                  {NECESSITY_LABELS[level]}
                </option>
              ))}
            </select>
          </Field>
        )}

        <Field label="Descrizione" htmlFor="tx-description" className="sm:col-span-2">
          <input id="tx-description" className="field" {...register('description')} />
        </Field>
      </div>

      {serverError && <ErrorBlock>{serverError}</ErrorBlock>}

      <div className="flex flex-wrap justify-end gap-2">
        <Button onClick={onDone}>Annulla</Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? 'Salvataggio…' : editing ? 'Salva modifiche' : isNewTransfer ? 'Crea giroconto' : 'Crea transazione'}
        </Button>
      </div>
    </form>
  )
}

export function TransactionFormDialog({ open, onClose, transaction }: Props) {
  return (
    <Dialog open={open} onClose={onClose} size="md" title={transaction ? 'Modifica transazione' : 'Nuova transazione'}>
      {/* Keyed so each opening starts from fresh defaults. */}
      <TransactionForm key={transaction?.id ?? 'new'} transaction={transaction} onDone={onClose} />
    </Dialog>
  )
}
