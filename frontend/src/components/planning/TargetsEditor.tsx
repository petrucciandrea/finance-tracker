import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { Tip } from '@/components/ui/Tip'
import { usePortfolioPresets, usePortfolioRules, useReplaceTargets } from '@/hooks/usePlanning'
import { useAllocation } from '@/hooks/usePortfolioAllocation'
import { apiErrorMessage } from '@/lib/apiError'
import { BUCKET_LABELS, bucketLabel } from '@/lib/exposures'
import { formatPercent, toNumber } from '@/lib/format'
import { rebalance, sumOf, type TargetMix } from '@/lib/targets'
import type { PortfolioPreset } from '@/types'

type TargetDimension = 'asset_class' | 'region'

// Buckets a target makes sense on: "no region" is what gold and crypto
// have, not a place to aim at.
function bucketsOf(dimension: TargetDimension): string[] {
  return Object.keys(BUCKET_LABELS[dimension]).filter((b) => b !== 'not_applicable')
}

function emptyMix(dimension: TargetDimension): TargetMix {
  return Object.fromEntries(bucketsOf(dimension).map((b) => [b, 0]))
}

function presetMix(preset: PortfolioPreset, dimension: TargetDimension): TargetMix {
  const mix = emptyMix(dimension)
  for (const t of preset.targets) if (t.dimension === dimension && t.bucket in mix) mix[t.bucket] = toNumber(t.target_pct)
  return mix
}

function DimensionEditor({ dimension, onDone }: { dimension: TargetDimension; onDone: () => void }) {
  const { data: status } = usePortfolioRules()
  const { data: presets } = usePortfolioPresets()
  const { data: allocation } = useAllocation(dimension, false)
  const replace = useReplaceTargets()

  const stored = (status?.rules ?? []).filter((r) => r.rule.kind === 'target' && r.rule.dimension === dimension)
  const [mix, setMix] = useState<TargetMix>(() => {
    const initial = emptyMix(dimension)
    for (const r of stored) if (r.rule.bucket && r.rule.bucket in initial) initial[r.rule.bucket] = toNumber(r.rule.target_pct)
    return initial
  })
  const [locked, setLocked] = useState<Set<string>>(new Set())
  const [tolerance, setTolerance] = useState(stored[0]?.rule.tolerance_pct ? String(toNumber(stored[0].rule.tolerance_pct)) : '5')
  const [error, setError] = useState<string | null>(null)

  const total = sumOf(mix)
  const actual = new Map((allocation?.buckets ?? []).map((b) => [b.bucket, b.percentage]))
  const usable = (presets ?? []).filter((p) => p.targets.some((t) => t.dimension === dimension))

  function move(bucket: string, value: number) {
    setMix((current) => rebalance(current, bucket, value, locked))
  }

  function toggleLock(bucket: string) {
    setLocked((current) => {
      const next = new Set(current)
      if (next.has(bucket)) next.delete(bucket)
      else next.add(bucket)
      return next
    })
  }

  async function save(targets: TargetMix) {
    setError(null)
    try {
      await replace.mutateAsync({
        dimension,
        tolerance_pct: tolerance.replace(',', '.'),
        targets: Object.entries(targets).map(([bucket, v]) => ({ bucket, target_pct: v.toFixed(1) })),
      })
      onDone()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare i target.'))
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {usable.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <span className="text-ink-2">Parti da:</span>
          {usable.map((p) => (
            <Button key={p.key} onClick={() => setMix(presetMix(p, dimension))} title={p.description}>
              {p.label}
            </Button>
          ))}
        </div>
      )}
      <ul className="flex flex-col gap-2.5">
        {bucketsOf(dimension).map((bucket) => {
          const label = bucketLabel(dimension, bucket)
          const isLocked = locked.has(bucket)
          const now = actual.get(bucket)
          return (
            <li key={bucket} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[170px_minmax(0,1fr)_auto]">
              <span className="text-[13px] font-bold">
                {label}
                {now !== undefined && <span className="block text-[12px] font-normal text-ink-3">ora {formatPercent(now)}</span>}
              </span>
              <input
                type="range"
                min={0}
                max={100}
                step={0.5}
                value={mix[bucket]}
                disabled={isLocked}
                aria-label={`Target ${label}`}
                onChange={(e) => move(bucket, Number(e.target.value))}
                className="order-3 col-span-2 w-full accent-accent sm:order-none sm:col-span-1"
              />
              <span className="flex items-center gap-1">
                <input
                  inputMode="decimal"
                  aria-label={`Target ${label} in percentuale`}
                  className="field h-9 w-[68px] py-0 text-right tabular-nums"
                  value={mix[bucket]}
                  disabled={isLocked}
                  onChange={(e) => {
                    const v = Number(e.target.value.replace(',', '.'))
                    if (!Number.isNaN(v)) move(bucket, v)
                  }}
                />
                <button
                  type="button"
                  aria-pressed={isLocked}
                  aria-label={isLocked ? `Sblocca ${label}` : `Blocca ${label}`}
                  title={isLocked ? 'Bloccato: non si muove quando sposti gli altri' : 'Blocca'}
                  onClick={() => toggleLock(bucket)}
                  className={`grid h-9 w-9 cursor-pointer place-items-center rounded-[10px] text-[14px] ${isLocked ? 'bg-accent-soft text-accent' : 'text-ink-3 hover:bg-card-2'}`}
                >
                  {isLocked ? '🔒' : '🔓'}
                </button>
              </span>
            </li>
          )
        })}
      </ul>
      <p className={`text-[13px] tabular-nums ${total > 100 ? 'font-bold text-neg' : 'text-ink-2'}`}>
        Totale {formatPercent(total)}
        {total < 100 && ` · ${formatPercent(100 - total)} senza target`}{' '}
        <Tip label="Come funzionano i cursori">
          {total === 100
            ? 'Muovendo un cursore gli altri si riproporzionano; quelli bloccati restano fermi.'
            : 'Arrivato al 100%, muovendo un cursore gli altri si riproporzionano.'}
        </Tip>
      </p>
      <Field label="Tolleranza (punti)" htmlFor="targets-tolerance" hint="Il banner avvisa solo fuori da target ± tolleranza.">
        <input id="targets-tolerance" inputMode="decimal" className="field w-[120px]" value={tolerance} onChange={(e) => setTolerance(e.target.value)} />
      </Field>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex flex-wrap justify-between gap-2">
        <Button onClick={() => save(emptyMix(dimension))} disabled={replace.isPending || stored.length === 0}>
          Togli i target
        </Button>
        <div className="flex gap-2">
          <Button onClick={onDone}>Annulla</Button>
          <Button variant="primary" onClick={() => save(mix)} disabled={replace.isPending || total > 100 || total === 0}>
            Salva
          </Button>
        </div>
      </div>
    </div>
  )
}

/**
 * The target mix of pillar 4, by asset class and by region. A preset only
 * loads its weights into the sliders; nothing is saved until "Salva".
 */
export function TargetsEditor({ onDone }: { onDone: () => void }) {
  const [dimension, setDimension] = useState<TargetDimension>('asset_class')
  return (
    <div className="flex flex-col gap-3">
      <SegmentedControl
        label="Target per"
        value={dimension}
        onChange={setDimension}
        options={[
          { value: 'asset_class', label: 'Asset class' },
          { value: 'region', label: 'Aree' },
        ]}
      />
      <p className="text-[12px] text-ink-3">
        I modelli sono esempi generici, non consigli, e non indicano prodotti: caricali e aggiustali come preferisci.
      </p>
      <DimensionEditor key={dimension} dimension={dimension} onDone={onDone} />
    </div>
  )
}
