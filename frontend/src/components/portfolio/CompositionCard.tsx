import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { CloseIcon } from '@/components/ui/Icon'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { StatusChip } from '@/components/ui/StatusChip'
import { Tip } from '@/components/ui/Tip'
import { getSuggestion } from '@/api/portfolioAllocation'
import { useAllocation, useAssetExposures, useResetExposures, useSaveExposures } from '@/hooks/usePortfolioAllocation'
import { apiErrorMessage } from '@/lib/apiError'
import { BUCKET_LABELS, DIMENSION_LABELS, SOURCE_LABELS, bucketLabel, isStale } from '@/lib/exposures'
import { formatAmount, formatFullDate, formatPercent, toISODate, toNumber } from '@/lib/format'
import type { AllocationPosition, Asset, ExposureDimension, ExposureWeight } from '@/types'

const DIMENSIONS: ExposureDimension[] = ['asset_class', 'region', 'sector', 'currency']

function WeightsEditor({ asset, dimension, onClose }: { asset: Asset; dimension: ExposureDimension; onClose: () => void }) {
  const { data, isLoading } = useAssetExposures(asset.id)
  const save = useSaveExposures()
  const reset = useResetExposures()
  const current = data?.dimensions.find((d) => d.dimension === dimension)
  const [rows, setRows] = useState<ExposureWeight[] | null>(null)
  const [asOf, setAsOf] = useState(toISODate(new Date()))
  const [error, setError] = useState<string | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const editing = rows ?? current?.weights ?? []
  const buckets = Object.keys(BUCKET_LABELS[dimension])
  const sum = editing.reduce((s, r) => s + toNumber(r.weight.replace(',', '.')), 0)

  function update(index: number, patch: Partial<ExposureWeight>) {
    setRows(editing.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  }

  async function suggest() {
    setError(null)
    setSuggesting(true)
    try {
      const suggestion = await getSuggestion(asset.id)
      const weights = suggestion.weights[dimension]
      if (weights?.length) setRows(weights)
      else setError('Yahoo non ha dati per questa dimensione: compilala a mano.')
    } catch (e) {
      setError(apiErrorMessage(e, 'Nessun suggerimento disponibile.'))
    } finally {
      setSuggesting(false)
    }
  }

  async function submit() {
    setError(null)
    try {
      await save.mutateAsync({
        assetId: asset.id,
        dimension,
        payload: { weights: editing.map((r) => ({ bucket: r.bucket, weight: r.weight.replace(',', '.') })), as_of: asOf },
      })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare i pesi.'))
    }
  }

  async function restore() {
    setError(null)
    try {
      await reset.mutateAsync({ assetId: asset.id, dimension })
      onClose()
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }

  if (isLoading) return <LoadingBlock className="h-32" />
  const unused = buckets.filter((b) => !editing.some((r) => r.bucket === b))

  return (
    <div className="flex flex-col gap-3">
      {current?.source && (
        <p className="text-[13px] text-ink-2">
          Ora: {SOURCE_LABELS[current.source]}
          {current.as_of && ` del ${formatFullDate(current.as_of)}`}.{current.notes && ` ${current.notes}`}
        </p>
      )}
      {current?.source_urls.length ? (
        <p className="text-[12px] text-ink-3">
          Fonti:{' '}
          {current.source_urls.map((url, i) => (
            <a key={url} href={url} target="_blank" rel="noreferrer" className="underline">
              {i > 0 && ', '}
              {new URL(url).hostname}
            </a>
          ))}
        </p>
      ) : null}
      <ul className="flex flex-col gap-2">
        {editing.map((row, i) => (
          <li key={row.bucket} className="grid grid-cols-[1fr_96px_44px] items-center gap-2">
            <label className="sr-only" htmlFor={`bucket-${i}`}>
              Voce
            </label>
            <select id={`bucket-${i}`} className="field" value={row.bucket} onChange={(e) => update(i, { bucket: e.target.value })}>
              {[row.bucket, ...unused].map((b) => (
                <option key={b} value={b}>
                  {bucketLabel(dimension, b)}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor={`weight-${i}`}>
              Peso percentuale
            </label>
            <input id={`weight-${i}`} inputMode="decimal" className="field" value={row.weight} onChange={(e) => update(i, { weight: e.target.value })} />
            <button
              type="button"
              aria-label="Rimuovi la voce"
              onClick={() => setRows(editing.filter((_, j) => j !== i))}
              className="grid h-11 w-11 cursor-pointer place-items-center rounded-[10px] text-ink-2 hover:bg-card-2"
            >
              <CloseIcon />
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
        <Button disabled={unused.length === 0} onClick={() => setRows([...editing, { bucket: unused[0], weight: '' }])}>
          + Voce
        </Button>
        <span className={sum > 100 ? 'font-bold text-neg' : 'text-ink-2'}>
          Totale {formatPercent(sum)}
          {sum < 100 && ` · ${formatPercent(100 - sum)} resta non classificato`}
        </span>
      </div>
      <Field label="Dati aggiornati al" htmlFor="weights-as-of" hint="La data del factsheet da cui li hai presi.">
        <input id="weights-as-of" type="date" className="field" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      </Field>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex flex-wrap justify-between gap-2">
        <div className="flex gap-2">
          {asset.asset_type === 'stock' && (
            <Button onClick={suggest} disabled={suggesting}>
              {suggesting ? 'Cerco…' : 'Suggerisci'}
            </Button>
          )}
          {current?.source === 'user' && (
            <Button onClick={restore} disabled={reset.isPending}>
              Ripristina
            </Button>
          )}
        </div>
        <div className="flex gap-2">
          <Button onClick={onClose}>Annulla</Button>
          <Button variant="primary" onClick={submit} disabled={save.isPending || editing.length === 0 || sum > 100}>
            Salva
          </Button>
        </div>
      </div>
    </div>
  )
}

function PositionRow({ position, dimension, currency, onEdit }: { position: AllocationPosition; dimension: ExposureDimension; currency: string; onEdit: () => void }) {
  const top = position.weights.slice(0, 3).map((w) => `${bucketLabel(dimension, w.bucket)} ${formatPercent(toNumber(w.weight), { digits: 0 })}`)
  return (
    <li className="flex items-center justify-between gap-3 border-t border-line py-2 text-[13px] first:border-t-0">
      <span className="min-w-0">
        <span className="font-bold">{position.label}</span>
        {position.account_name && position.kind !== 'cash' && <span className="text-ink-3"> · {position.account_name}</span>}
        <span className="block text-ink-2">{top.length ? top.join(' · ') : 'Non classificato'}</span>
      </span>
      <span className="flex flex-none items-center gap-2">
        {position.source === null && position.kind === 'holding' && <StatusChip kind="warn">Da classificare</StatusChip>}
        {isStale(position.as_of) && <StatusChip kind="warn">Dati vecchi</StatusChip>}
        <span className="tabular-nums text-ink-2">{position.value === null ? 'senza prezzo' : `${formatAmount(position.value, currency, { digits: 0 })} ${currency}`}</span>
        {position.kind === 'holding' && position.asset && <Button onClick={onEdit}>Modifica</Button>}
      </span>
    </li>
  )
}

/**
 * What the long-term portfolio is made of. Holdings set aside for the
 * emergency fund, a dated goal or the taxes are out: they are pillars 2-3.
 */
export function CompositionCard() {
  const [dimension, setDimension] = useState<ExposureDimension>('asset_class')
  const [includeCash, setIncludeCash] = useState(false)
  const [editing, setEditing] = useState<Asset | null>(null)
  const { data, isLoading, isError } = useAllocation(dimension, includeCash)
  const currency = data?.base_currency ?? ''
  const max = Math.max(1, ...(data?.buckets ?? []).map((b) => b.percentage))

  return (
    <Card
      title="Composizione"
      meta={<span className="text-[13px] text-ink-3">Solo gli investimenti di lungo periodo</span>}
      action={
        <SegmentedControl
          label="Dimensione"
          size="sm"
          value={dimension}
          onChange={setDimension}
          options={DIMENSIONS.map((d) => ({ value: d, label: DIMENSION_LABELS[d] }))}
        />
      }
    >
      {(dimension === 'asset_class' || dimension === 'currency') && (
        <label className="mt-2 flex items-center gap-2 text-[13px] text-ink-2">
          <input type="checkbox" className="h-[18px] w-[18px] accent-accent" checked={includeCash} onChange={(e) => setIncludeCash(e.target.checked)} />
          Includi la liquidità sui conti d’investimento
        </label>
      )}
      {isLoading ? (
        <LoadingBlock className="mt-3 h-40" />
      ) : isError || !data ? (
        <div className="mt-3">
          <ErrorBlock>Non è stato possibile calcolare la composizione.</ErrorBlock>
        </div>
      ) : toNumber(data.total) === 0 && data.positions.length === 0 ? (
        <div className="mt-3">
          <EmptyState title="Nessun investimento di lungo periodo" />
        </div>
      ) : (
        <>
          <div className="mt-3 flex flex-col gap-2">
            {data.coverage < 90 && (
              <Notice>
                Classificato il {formatPercent(data.coverage, { digits: 0 })} del valore: completa le posizioni «Da classificare» perché i paletti del Piano
                possano giudicare questa dimensione.
              </Notice>
            )}
            {data.stale_count > 0 && <Notice>{data.stale_count} posizioni hanno pesi di più di un anno fa: aggiornali dal factsheet.</Notice>}
            {data.has_unpriced && <Notice>Alcune posizioni non hanno un prezzo salvato e non sono contate.</Notice>}
          </div>
          <ul className="mt-3 flex flex-col gap-1.5 tabular-nums">
            {data.buckets.map((b) => (
              <li key={b.bucket} className="grid grid-cols-[minmax(110px,180px)_1fr_auto] items-center gap-2 text-[13px]">
                <span className="truncate font-bold">{bucketLabel(dimension, b.bucket)}</span>
                <span className="h-2 rounded-full bg-track" aria-hidden="true">
                  <span className="block h-full rounded-full bg-bar" style={{ width: `${(b.percentage / max) * 100}%` }} />
                </span>
                <span className="text-ink-2">
                  {formatPercent(b.percentage)} · {formatAmount(b.value, currency, { digits: 0 })} {currency}
                </span>
              </li>
            ))}
            {toNumber(data.unclassified_value) > 0 && (
              <li className="grid grid-cols-[minmax(110px,180px)_1fr_auto] items-center gap-2 text-[13px] text-ink-3">
                <span className="font-bold">Non classificato</span>
                <span />
                <span>
                  {formatPercent(100 - data.coverage)} · {formatAmount(data.unclassified_value, currency, { digits: 0 })} {currency}
                </span>
              </li>
            )}
          </ul>
          <p className="mt-2 text-[12px] text-ink-3">
            Come leggere le percentuali{' '}
            <Tip label="Come leggere le percentuali">
              {dimension === 'sector' && <span>Percentuali sulla sola parte azionaria.</span>}
              {dimension === 'region' && toNumber(data.outside_value) > 0 && (
                <span>
                  Percentuali su ciò che ha un'area: esclusi {formatAmount(data.outside_value, currency, { digits: 0 })} {currency} di oro, crypto e
                  monetario.
                </span>
              )}
              {toNumber(data.excluded_value) > 0 && (
                <span>
                  Esclusi {formatAmount(data.excluded_value, currency, { digits: 0 })} {currency} accantonati per fondo emergenza, obiettivi a scadenza
                  o tasse.
                </span>
              )}
              <span>Le sovrapposizioni dentro gli ETF (lo stesso titolo in due fondi) non sono visibili.</span>
            </Tip>
          </p>
          <details className="mt-3">
            <summary className="cursor-pointer text-[13px] font-extrabold">Posizioni e pesi</summary>
            <ul className="mt-2">
              {data.positions.map((p) => (
                <PositionRow key={`${p.kind}-${p.label}-${p.account_name}`} position={p} dimension={dimension} currency={currency} onEdit={() => setEditing(p.asset)} />
              ))}
            </ul>
          </details>
        </>
      )}
      <Dialog open={!!editing} onClose={() => setEditing(null)} title={`${editing?.symbol ?? ''} · ${DIMENSION_LABELS[dimension]}`} size="md">
        {editing && <WeightsEditor key={`${editing.id}-${dimension}`} asset={editing} dimension={dimension} onClose={() => setEditing(null)} />}
      </Dialog>
    </Card>
  )
}
