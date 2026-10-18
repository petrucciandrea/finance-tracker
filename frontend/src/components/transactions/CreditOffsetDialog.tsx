import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import { useCreateCreditOffset } from '@/hooks/useTransactions'
import { apiErrorMessage } from '@/lib/apiError'
import { NECESSITY_LABELS } from '@/lib/categories'
import { formatAmount, toISODate, toNumber } from '@/lib/format'
import type { NecessityLevel, Transaction } from '@/types'

function parseAmount(value: string): number {
  return Number(value.replace(',', '.'))
}

function makeSchema(open: number) {
  return z.object({
    account_id: z.string().min(1, 'Seleziona un conto'),
    amount: z
      .string()
      .min(1, 'Importo obbligatorio')
      .refine((v) => Number.isFinite(parseAmount(v)) && parseAmount(v) > 0, 'Inserisci un importo maggiore di zero')
      .refine((v) => parseAmount(v) <= open, `Non può superare il credito aperto (${open})`),
    date: z.string().min(1, 'Data obbligatoria'),
    category_id: z.string().optional(),
    necessity_level_override: z.enum(['primary', 'useful', 'discretionary']).or(z.literal('')).optional(),
    description: z.string().optional(),
  })
}

type FormValues = z.infer<ReturnType<typeof makeSchema>>

/**
 * The friend paid the next time instead of handing cash back: the user's share
 * of that is a real spend and it closes that much of the credit. The backend
 * writes both on one account, so the balance doesn't move.
 */
function CreditOffsetForm({ credit, onDone }: { credit: Transaction; onDone: () => void }) {
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const createOffset = useCreateCreditOffset()
  const [serverError, setServerError] = useState<string | null>(null)
  const open = toNumber(credit.lent_amount) - toNumber(credit.repaid_amount)
  // The repayment must share the expense's currency, and a closed account
  // refuses movements dated after the close.
  const candidates = (accounts ?? []).filter((a) => !a.deleted_at && !a.closed_at && a.currency === credit.currency)
  const today = toISODate(new Date())

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(makeSchema(open)),
    defaultValues: {
      account_id: candidates.find((a) => a.id === credit.account_id)?.id ?? '',
      amount: String(open),
      date: today < credit.date ? credit.date : today,
      category_id: '',
      necessity_level_override: '',
      description: '',
    },
  })

  async function onSubmit(values: FormValues) {
    setServerError(null)
    try {
      await createOffset.mutateAsync({
        credit_transaction_id: credit.id,
        account_id: values.account_id,
        category_id: values.category_id || null,
        amount: String(parseAmount(values.amount)),
        date: values.date,
        description: values.description || null,
        necessity_level_override: values.necessity_level_override || null,
      })
      onDone()
    } catch (error) {
      setServerError(apiErrorMessage(error))
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
      <p className="text-[14px] text-ink-2">
        Per <b>{credit.description || 'questa spesa'}</b> restano da incassare{' '}
        <b>
          {formatAmount(open, credit.currency)} {credit.currency}
        </b>
        . Se invece di restituirli ha pagato lui qualcosa per te, registra qui la tua quota: conta come spesa e chiude il credito, senza entrate e senza
        muovere il saldo.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Quota che avrebbe pagato lui" htmlFor="off-amount" error={errors.amount?.message}>
          <input
            id="off-amount"
            inputMode="decimal"
            aria-invalid={!!errors.amount}
            aria-describedby="off-amount-msg"
            className="field tabular-nums"
            {...register('amount')}
          />
        </Field>
        <Field label="Data" htmlFor="off-date" error={errors.date?.message}>
          <input id="off-date" type="date" min={credit.date} aria-invalid={!!errors.date} className="field" {...register('date')} />
        </Field>
        <Field
          label="Conto"
          htmlFor="off-account"
          error={errors.account_id?.message}
          hint={`Solo conti in ${credit.currency}. Le due righe si annullano: il saldo non cambia.`}
        >
          <select id="off-account" aria-invalid={!!errors.account_id} aria-describedby="off-account-msg" className="field" {...register('account_id')}>
            <option value="">Seleziona un conto</option>
            {candidates.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {a.currency}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Categoria della spesa" htmlFor="off-category" hint="Se la lasci vuota finisce in “Varie”.">
          <CategorySelect id="off-category" aria-describedby="off-category-msg" categories={categories} type="expense" emptyLabel="Nessuna (Varie)" {...register('category_id')} />
        </Field>
        <Field label="Livello di necessità" htmlFor="off-necessity">
          <select id="off-necessity" className="field" {...register('necessity_level_override')}>
            <option value="">Eredita dalla categoria</option>
            {(Object.keys(NECESSITY_LABELS) as NecessityLevel[]).map((level) => (
              <option key={level} value={level}>
                {NECESSITY_LABELS[level]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Descrizione" htmlFor="off-description">
          <input id="off-description" className="field" placeholder="Compensazione" {...register('description')} />
        </Field>
      </div>

      {serverError && <ErrorBlock>{serverError}</ErrorBlock>}

      <div className="flex flex-wrap justify-end gap-2">
        <Button onClick={onDone}>Annulla</Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? 'Salvataggio…' : 'Compensa'}
        </Button>
      </div>
    </form>
  )
}

export function CreditOffsetDialog({ credit, onClose }: { credit: Transaction | null; onClose: () => void }) {
  return (
    <Dialog open={!!credit} onClose={onClose} size="md" title="Compensa con una spesa">
      {/* Keyed so each opening starts from fresh defaults. */}
      {credit && <CreditOffsetForm key={credit.id} credit={credit} onDone={onClose} />}
    </Dialog>
  )
}
