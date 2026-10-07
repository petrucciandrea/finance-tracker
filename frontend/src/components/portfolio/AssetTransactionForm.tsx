import { useState } from 'react'
import { buttonClass } from '@/lib/buttonClass'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { isAxiosError } from 'axios'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import { useCreateAssetTransaction } from '@/hooks/useAssetTransactions'
import { useHoldings, useSearchAssets } from '@/hooks/usePortfolio'
import type { ApiErrorResponse, AssetType } from '@/types'

const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  stock: 'Azione',
  etf: 'ETF',
  crypto: 'Crypto',
}

const positiveNumber = (v: string) => !Number.isNaN(Number(v)) && Number(v) > 0

const assetTransactionSchema = z.object({
  account_id: z.string().min(1, 'Seleziona un conto'),
  asset_type: z.enum(['stock', 'etf', 'crypto']),
  symbol: z.string().min(1, 'Inserisci un simbolo').max(20),
  type: z.enum(['buy', 'sell']),
  quantity: z
    .string()
    .min(1, 'Quantità obbligatoria')
    .refine(positiveNumber, 'Inserisci un numero positivo'),
  price: z
    .string()
    .min(1, 'Prezzo obbligatorio')
    .refine(positiveNumber, 'Inserisci un numero positivo'),
  fee: z
    .string()
    .optional()
    .refine((v) => !v || (!Number.isNaN(Number(v)) && Number(v) >= 0), 'Inserisci un numero valido'),
  date: z.string().min(1, 'Data obbligatoria'),
  notes: z.string().optional(),
  category_id: z.string().optional(),
})

type AssetTransactionFormValues = z.infer<typeof assetTransactionSchema>

export function AssetTransactionForm({ onDone }: { onDone: () => void }) {
  const { data: accounts } = useAccounts()
  const { data: holdings } = useHoldings()
  const { data: categories } = useCategories()
  const [formError, setFormError] = useState<string | null>(null)
  const createAssetTransaction = useCreateAssetTransaction()

  const {
    register,
    handleSubmit,
    reset,
    control,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<AssetTransactionFormValues>({
    resolver: zodResolver(assetTransactionSchema),
    defaultValues: {
      asset_type: 'stock',
      type: 'buy',
      date: new Date().toISOString().slice(0, 10),
    },
  })

  // useWatch rather than watch(): watch() opts the whole component out of
  // React Compiler memoization (react-hooks/incompatible-library).
  const selectedAccountId = useWatch({ control, name: 'account_id' })
  const selectedAssetType = useWatch({ control, name: 'asset_type' })
  const selectedType = useWatch({ control, name: 'type' })
  const symbolQuery = useWatch({ control, name: 'symbol' }) ?? ''
  const { data: searchResults } = useSearchAssets(symbolQuery, selectedAssetType)

  // Holdings only make sense on investment/crypto accounts — the backend
  // rejects anything else with a 422, filtering here avoids the round-trip.
  const eligibleAccounts = (accounts ?? []).filter(
    (a) => (a.type === 'investment' || a.type === 'crypto_wallet') && !a.closed_at,
  )

  const matchingHolding = holdings?.find(
    (h) =>
      h.account_id === selectedAccountId &&
      h.asset.asset_type === selectedAssetType &&
      h.asset.symbol === symbolQuery.toUpperCase(),
  )
  const heldQuantity = matchingHolding ? Number(matchingHolding.quantity) : 0

  async function onSubmit(values: AssetTransactionFormValues) {
    setFormError(null)

    if (values.type === 'sell' && Number(values.quantity) > heldQuantity) {
      setFormError(`Non puoi vendere ${values.quantity} — ne possiedi solo ${heldQuantity}`)
      return
    }

    try {
      await createAssetTransaction.mutateAsync({
        account_id: values.account_id,
        symbol: values.symbol,
        asset_type: values.asset_type,
        type: values.type,
        quantity: values.quantity,
        price: values.price,
        fee: values.fee || '0',
        date: values.date,
        notes: values.notes || null,
        category_id: values.category_id || null,
      })
      reset({
        asset_type: values.asset_type,
        type: 'buy',
        date: new Date().toISOString().slice(0, 10),
        account_id: values.account_id,
        // Kept like the account: a run of buys usually shares one category.
        category_id: values.category_id,
      })
      onDone()
    } catch (error) {
      if (isAxiosError<ApiErrorResponse>(error) && error.response) {
        setFormError(
          error.response.data?.error?.message ?? 'Impossibile registrare la transazione. Riprova.',
        )
      } else {
        setFormError('Impossibile registrare la transazione. Riprova.')
      }
    }
  }

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      className="grid grid-cols-1 gap-4 rounded-[14px] border border-line bg-card px-4 py-4 sm:grid-cols-4 sm:px-5"
      noValidate
    >
      <div>
        <label htmlFor="account_id" className="mb-1.5 block text-[14px] font-bold text-ink">
          Conto
        </label>
        <select
          id="account_id"
          {...register('account_id')}
          className="field"
        >
          <option value="">Seleziona...</option>
          {eligibleAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.currency})
            </option>
          ))}
        </select>
        {errors.account_id && <p role="alert" className="mt-1.5 text-[13px] font-bold text-neg">{errors.account_id.message}</p>}
      </div>

      <div>
        <label htmlFor="asset_type" className="mb-1.5 block text-[14px] font-bold text-ink">
          Tipo asset
        </label>
        <select
          id="asset_type"
          {...register('asset_type')}
          className="field"
        >
          {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <div className="relative">
        <label htmlFor="symbol" className="mb-1.5 block text-[14px] font-bold text-ink">
          Simbolo
        </label>
        <input
          id="symbol"
          autoComplete="off"
          {...register('symbol')}
          className="field uppercase"
        />
        {selectedAssetType === 'crypto' ? (
          searchResults &&
          searchResults.length > 0 && (
            <ul className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-[10px] border border-line bg-card text-[14px] shadow-[0_12px_32px_rgba(0,0,0,0.18)]">
              {searchResults.map((result) => (
                <li key={result.symbol}>
                  <button
                    type="button"
                    onClick={() => setValue('symbol', result.symbol)}
                    className="block min-h-11 w-full cursor-pointer px-3 py-2 text-left hover:bg-card-2"
                  >
                    <span className="font-bold">{result.symbol}</span>{' '}
                    <span className="text-ink-3">{result.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : (
          <p className="mt-1.5 text-[13px] text-ink-3">Inserisci il ticker esatto (es. AAPL)</p>
        )}
        {errors.symbol && <p role="alert" className="mt-1.5 text-[13px] font-bold text-neg">{errors.symbol.message}</p>}
      </div>

      <div>
        <label htmlFor="type" className="mb-1.5 block text-[14px] font-bold text-ink">
          Operazione
        </label>
        <select
          id="type"
          {...register('type')}
          className="field"
        >
          <option value="buy">Acquisto</option>
          <option value="sell">Vendita</option>
        </select>
        {selectedType === 'sell' && (
          <p className="mt-1.5 text-[13px] text-ink-3">Attualmente in possesso: {heldQuantity}</p>
        )}
      </div>

      <div>
        <label htmlFor="quantity" className="mb-1.5 block text-[14px] font-bold text-ink">
          Quantità
        </label>
        <input
          id="quantity"
          {...register('quantity')}
          className="field"
        />
        {errors.quantity && <p role="alert" className="mt-1.5 text-[13px] font-bold text-neg">{errors.quantity.message}</p>}
      </div>

      <div>
        <label htmlFor="price" className="mb-1.5 block text-[14px] font-bold text-ink">
          Prezzo unitario
        </label>
        <input
          id="price"
          {...register('price')}
          className="field"
        />
        {errors.price && <p role="alert" className="mt-1.5 text-[13px] font-bold text-neg">{errors.price.message}</p>}
      </div>

      <div>
        <label htmlFor="fee" className="mb-1.5 block text-[14px] font-bold text-ink">
          Commissioni (opzionale)
        </label>
        <input
          id="fee"
          placeholder="0"
          {...register('fee')}
          className="field"
        />
        {errors.fee && <p role="alert" className="mt-1.5 text-[13px] font-bold text-neg">{errors.fee.message}</p>}
      </div>

      <div>
        <label htmlFor="date" className="mb-1.5 block text-[14px] font-bold text-ink">
          Data
        </label>
        <input
          id="date"
          type="date"
          {...register('date')}
          className="field"
        />
        {errors.date && <p role="alert" className="mt-1.5 text-[13px] font-bold text-neg">{errors.date.message}</p>}
      </div>

      <div>
        <label htmlFor="category_id" className="mb-1.5 block text-[14px] font-bold text-ink">
          Categoria (opzionale)
        </label>
        <CategorySelect
          id="category_id"
          categories={categories}
          type="transfer"
          emptyLabel="Nessuna"
          {...register('category_id')}
        />
        <p className="mt-1.5 text-[13px] text-ink-3">Va sul movimento di cassa; resta fuori da totali e piano.</p>
      </div>

      <div className="sm:col-span-3">
        <label htmlFor="notes" className="mb-1.5 block text-[14px] font-bold text-ink">
          Note (opzionale)
        </label>
        <input
          id="notes"
          {...register('notes')}
          className="field"
        />
      </div>

      <div className="sm:col-span-4">
        {formError && <p role="alert" className="mb-2 rounded-[10px] bg-neg-soft px-3 py-2 text-[13px] font-bold text-neg">{formError}</p>}
        <button
          type="submit"
          disabled={isSubmitting}
          className={buttonClass('primary')}
        >
          {isSubmitting ? 'Registrazione...' : 'Registra transazione'}
        </button>
      </div>
    </form>
  )
}
