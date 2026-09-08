import { useTransactionSummary } from '@/hooks/useTransactions'

function formatMonthLabel(month: string): string {
  // "2026-09" -> "Settembre 2026"
  const [year, monthNum] = month.split('-')
  const date = new Date(Number(year), Number(monthNum) - 1)
  return date.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' })
}

export function DashboardPage() {
  const now = new Date()
  const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10)

  const { data, isLoading, isError } = useTransactionSummary({
    group_by: ['category', 'month'],
    date_from: firstOfMonth,
  })

  const totalThisMonth = data?.data.reduce(
    (sum, item) => sum + Number(item.total_amount_base_currency),
    0,
  )

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-800">Dashboard</h1>

      {isLoading && <p className="text-slate-500">Caricamento...</p>}
      {isError && <p className="text-red-600">Errore nel caricamento dei dati.</p>}

      {data && (
        <>
          <div className="rounded-lg bg-white p-6 shadow-sm">
            <p className="text-sm text-slate-500">Totale questo mese</p>
            <p
              className={`mt-1 text-3xl font-semibold ${
                (totalThisMonth ?? 0) < 0 ? 'text-red-600' : 'text-green-600'
              }`}
            >
              {(totalThisMonth ?? 0).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' })}
            </p>
          </div>

          <div className="rounded-lg bg-white p-6 shadow-sm">
            <h2 className="mb-4 text-lg font-medium text-slate-800">Per categoria</h2>
            {data.data.length === 0 ? (
              <p className="text-sm text-slate-500">Nessuna transazione questo mese.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {data.data.map((item) => (
                  <li
                    key={`${item.category_id}-${item.month}`}
                    className="flex items-center justify-between py-3"
                  >
                    <div>
                      <p className="text-sm font-medium text-slate-800">
                        {item.category_name ?? 'Senza categoria'}
                      </p>
                      {item.month && (
                        <p className="text-xs text-slate-400">{formatMonthLabel(item.month)}</p>
                      )}
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold text-slate-800">
                        {Number(item.total_amount_base_currency).toLocaleString('it-IT', {
                          style: 'currency',
                          currency: 'EUR',
                        })}
                      </p>
                      <p className="text-xs text-slate-400">{item.transaction_count} transazioni</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}
