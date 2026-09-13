import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { isAxiosError } from 'axios'
import { useAccounts } from '@/hooks/useAccounts'
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
})

type AssetTransactionFormValues = z.infer<typeof assetTransactionSchema>

export function AssetTransactionForm({ onDone }: { onDone: () => void }) {
  const { data: accounts } = useAccounts()
  const { data: holdings } = useHoldings()
  const [formError, setFormError] = useState<string | null>(null)
  const createAssetTransaction = useCreateAssetTransaction()

  const {
    register,
    handleSubmit,
    reset,
    watch,
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

  const selectedAccountId = watch('account_id')
  const selectedAssetType = watch('asset_type')
  const selectedType = watch('type')
  const symbolQuery = watch('symbol') ?? ''
  const { data: searchResults } = useSearchAssets(symbolQuery, selectedAssetType)

  // Holdings only make sense on investment/crypto accounts — the backend
  // rejects anything else with a 422, filtering here avoids the round-trip.
  const eligibleAccounts = (accounts ?? []).filter(
    (a) => a.type === 'investment' || a.type === 'crypto_wallet',
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
      })
      reset({
        asset_type: values.asset_type,
        type: 'buy',
        date: new Date().toISOString().slice(0, 10),
        account_id: values.account_id,
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
      className="grid grid-cols-1 gap-4 rounded-lg bg-white p-6 shadow-sm sm:grid-cols-4"
      noValidate
    >
      <div>
        <label htmlFor="account_id" className="block text-sm font-medium text-slate-700">
          Conto
        </label>
        <select
          id="account_id"
          {...register('account_id')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          <option value="">Seleziona...</option>
          {eligibleAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.currency})
            </option>
          ))}
        </select>
        {errors.account_id && <p className="mt-1 text-sm text-red-600">{errors.account_id.message}</p>}
      </div>

      <div>
        <label htmlFor="asset_type" className="block text-sm font-medium text-slate-700">
          Tipo asset
        </label>
        <select
          id="asset_type"
          {...register('asset_type')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <div className="relative">
        <label htmlFor="symbol" className="block text-sm font-medium text-slate-700">
          Simbolo
        </label>
        <input
          id="symbol"
          autoComplete="off"
          {...register('symbol')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm uppercase focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        {selectedAssetType === 'crypto' ? (
          searchResults &&
          searchResults.length > 0 && (
            <ul className="absolute z-10 mt-1 max-h-40 w-full overflow-auto rounded-md border border-slate-200 bg-white text-sm shadow-md">
              {searchResults.map((result) => (
                <li key={result.symbol}>
                  <button
                    type="button"
                    onClick={() => setValue('symbol', result.symbol)}
                    className="block w-full px-3 py-2 text-left hover:bg-slate-50"
                  >
                    <span className="font-medium">{result.symbol}</span>{' '}
                    <span className="text-slate-400">{result.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : (
          <p className="mt-1 text-xs text-slate-400">Inserisci il ticker esatto (es. AAPL)</p>
        )}
        {errors.symbol && <p className="mt-1 text-sm text-red-600">{errors.symbol.message}</p>}
      </div>

      <div>
        <label htmlFor="type" className="block text-sm font-medium text-slate-700">
          Operazione
        </label>
        <select
          id="type"
          {...register('type')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          <option value="buy">Acquisto</option>
          <option value="sell">Vendita</option>
        </select>
        {selectedType === 'sell' && (
          <p className="mt-1 text-xs text-slate-400">Attualmente in possesso: {heldQuantity}</p>
        )}
      </div>

      <div>
        <label htmlFor="quantity" className="block text-sm font-medium text-slate-700">
          Quantità
        </label>
        <input
          id="quantity"
          {...register('quantity')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        {errors.quantity && <p className="mt-1 text-sm text-red-600">{errors.quantity.message}</p>}
      </div>

      <div>
        <label htmlFor="price" className="block text-sm font-medium text-slate-700">
          Prezzo unitario
        </label>
        <input
          id="price"
          {...register('price')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        {errors.price && <p className="mt-1 text-sm text-red-600">{errors.price.message}</p>}
      </div>

      <div>
        <label htmlFor="fee" className="block text-sm font-medium text-slate-700">
          Commissioni (opzionale)
        </label>
        <input
          id="fee"
          placeholder="0"
          {...register('fee')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        {errors.fee && <p className="mt-1 text-sm text-red-600">{errors.fee.message}</p>}
      </div>

      <div>
        <label htmlFor="date" className="block text-sm font-medium text-slate-700">
          Data
        </label>
        <input
          id="date"
          type="date"
          {...register('date')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        {errors.date && <p className="mt-1 text-sm text-red-600">{errors.date.message}</p>}
      </div>

      <div className="sm:col-span-4">
        <label htmlFor="notes" className="block text-sm font-medium text-slate-700">
          Note (opzionale)
        </label>
        <input
          id="notes"
          {...register('notes')}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
      </div>

      <div className="sm:col-span-4">
        {formError && <p className="mb-2 text-sm text-red-600">{formError}</p>}
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {isSubmitting ? 'Registrazione...' : 'Registra transazione'}
        </button>
      </div>
    </form>
  )
}
