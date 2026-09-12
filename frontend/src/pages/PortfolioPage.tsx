import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { useAccounts } from '@/hooks/useAccounts'
import {
  useCreateHolding,
  useDeleteHolding,
  useHoldings,
  useNetWorth,
  useSearchAssets,
} from '@/hooks/usePortfolio'
import type { AssetType } from '@/types'

const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  stock: 'Azione',
  etf: 'ETF',
  crypto: 'Crypto',
}

const ALLOCATION_COLORS = ['#1e293b', '#059669'] // slate-800 (cash), emerald-600 (holdings)

const holdingSchema = z.object({
  account_id: z.string().min(1, 'Seleziona un conto'),
  asset_type: z.enum(['stock', 'etf', 'crypto']),
  symbol: z.string().min(1, 'Inserisci un simbolo').max(20),
  quantity: z
    .string()
    .min(1, 'Quantità obbligatoria')
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, 'Inserisci un numero positivo'),
  avg_buy_price: z
    .string()
    .min(1, 'Prezzo obbligatorio')
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, 'Inserisci un numero positivo'),
})

type HoldingFormValues = z.infer<typeof holdingSchema>

function formatCurrency(amount: string, currency: string): string {
  return Number(amount).toLocaleString('it-IT', { style: 'currency', currency })
}

export function PortfolioPage() {
  const { data: accounts } = useAccounts()
  const { data: holdings, isLoading, isError } = useHoldings()
  const { data: netWorth } = useNetWorth()
  const [isFormOpen, setIsFormOpen] = useState(false)

  const createHolding = useCreateHolding()
  const deleteHolding = useDeleteHolding()

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<HoldingFormValues>({
    resolver: zodResolver(holdingSchema),
    defaultValues: { asset_type: 'stock' },
  })

  const selectedAssetType = watch('asset_type')
  const symbolQuery = watch('symbol') ?? ''
  const { data: searchResults } = useSearchAssets(symbolQuery, selectedAssetType)

  // Holdings only make sense on investment/crypto accounts — the backend
  // rejects anything else with a 422, filtering here avoids the round-trip.
  const eligibleAccounts = (accounts ?? []).filter(
    (a) => a.type === 'investment' || a.type === 'crypto_wallet',
  )

  async function onSubmit(values: HoldingFormValues) {
    await createHolding.mutateAsync(values)
    reset({ asset_type: values.asset_type })
    setIsFormOpen(false)
  }

  async function handleDelete(id: string, symbol: string) {
    if (!window.confirm(`Eliminare la posizione "${symbol}"?`)) return
    await deleteHolding.mutateAsync(id)
  }

  const allocationData = netWorth
    ? [
        { name: 'Liquidità', value: Number(netWorth.total_cash_balance) },
        { name: 'Investimenti', value: Number(netWorth.total_holdings_value) },
      ].filter((slice) => slice.value > 0)
    : []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Portfolio</h1>
        <button
          onClick={() => setIsFormOpen((open) => !open)}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          {isFormOpen ? 'Annulla' : 'Nuova posizione'}
        </button>
      </div>

      {netWorth && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg bg-white p-6 shadow-sm">
            <p className="text-xs font-medium uppercase text-slate-400">Patrimonio netto</p>
            <p className="mt-1 text-2xl font-semibold text-slate-800">
              {formatCurrency(netWorth.total_net_worth, netWorth.base_currency)}
            </p>
          </div>
          <div className="rounded-lg bg-white p-6 shadow-sm">
            <p className="text-xs font-medium uppercase text-slate-400">Liquidità</p>
            <p className="mt-1 text-2xl font-semibold text-slate-800">
              {formatCurrency(netWorth.total_cash_balance, netWorth.base_currency)}
            </p>
          </div>
          <div className="rounded-lg bg-white p-6 shadow-sm">
            <p className="text-xs font-medium uppercase text-slate-400">Investimenti</p>
            <p className="mt-1 text-2xl font-semibold text-slate-800">
              {formatCurrency(netWorth.total_holdings_value, netWorth.base_currency)}
            </p>
          </div>
        </div>
      )}

      {allocationData.length > 0 && (
        <div className="rounded-lg bg-white p-6 shadow-sm">
          <p className="mb-4 text-sm font-medium text-slate-700">Allocazione</p>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={allocationData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={2}
                >
                  {allocationData.map((slice, index) => (
                    <Cell key={slice.name} fill={ALLOCATION_COLORS[index % ALLOCATION_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value) =>
                    netWorth ? formatCurrency(String(value), netWorth.base_currency) : value
                  }
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {isFormOpen && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="grid grid-cols-1 gap-4 rounded-lg bg-white p-6 shadow-sm sm:grid-cols-5"
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
            {errors.account_id && (
              <p className="mt-1 text-sm text-red-600">{errors.account_id.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="asset_type" className="block text-sm font-medium text-slate-700">
              Tipo
            </label>
            <select
              id="asset_type"
              {...register('asset_type')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="stock">Azione</option>
              <option value="etf">ETF</option>
              <option value="crypto">Crypto</option>
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
              searchResults && searchResults.length > 0 && (
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
            <label htmlFor="quantity" className="block text-sm font-medium text-slate-700">
              Quantità
            </label>
            <input
              id="quantity"
              {...register('quantity')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.quantity && (
              <p className="mt-1 text-sm text-red-600">{errors.quantity.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="avg_buy_price" className="block text-sm font-medium text-slate-700">
              Prezzo medio
            </label>
            <input
              id="avg_buy_price"
              {...register('avg_buy_price')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.avg_buy_price && (
              <p className="mt-1 text-sm text-red-600">{errors.avg_buy_price.message}</p>
            )}
          </div>

          <div className="sm:col-span-5">
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {isSubmitting ? 'Creazione...' : 'Aggiungi posizione'}
            </button>
          </div>
        </form>
      )}

      <div className="overflow-x-auto rounded-lg bg-white shadow-sm">
        {isLoading && <p className="p-6 text-slate-500">Caricamento...</p>}
        {isError && <p className="p-6 text-red-600">Errore nel caricamento del portfolio.</p>}

        {holdings && holdings.length === 0 && (
          <p className="p-6 text-sm text-slate-500">
            Nessuna posizione ancora. Aggiungine una per iniziare.
          </p>
        )}

        {holdings && holdings.length > 0 && (
          <table className="min-w-full divide-y divide-slate-100 text-sm">
            <thead>
              <tr className="text-left text-xs font-medium uppercase text-slate-400">
                <th className="px-4 py-3">Asset</th>
                <th className="px-4 py-3">Tipo</th>
                <th className="px-4 py-3">Quantità</th>
                <th className="px-4 py-3">Prezzo medio</th>
                <th className="px-4 py-3">Prezzo attuale</th>
                <th className="px-4 py-3">Valore</th>
                <th className="px-4 py-3">P&L</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {holdings.map((holding) => (
                <tr key={holding.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-800">{holding.asset.symbol}</p>
                    <p className="text-xs text-slate-400">{holding.asset.name}</p>
                  </td>
                  <td className="px-4 py-3">{ASSET_TYPE_LABELS[holding.asset.asset_type]}</td>
                  <td className="px-4 py-3">{holding.quantity}</td>
                  <td className="px-4 py-3">
                    {formatCurrency(holding.avg_buy_price, holding.asset.currency)}
                  </td>
                  <td className="px-4 py-3">
                    {formatCurrency(holding.current_price, holding.asset.currency)}
                  </td>
                  <td className="px-4 py-3">
                    {formatCurrency(holding.market_value, holding.asset.currency)}
                  </td>
                  <td
                    className={
                      Number(holding.unrealized_pnl) < 0
                        ? 'px-4 py-3 text-red-600'
                        : 'px-4 py-3 text-green-600'
                    }
                  >
                    {formatCurrency(holding.unrealized_pnl, holding.asset.currency)} (
                    {holding.unrealized_pnl_percentage}%)
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleDelete(holding.id, holding.asset.symbol)}
                      className="text-sm font-medium text-red-600 hover:underline"
                    >
                      Elimina
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
