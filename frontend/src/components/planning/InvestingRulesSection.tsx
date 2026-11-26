import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { CloseIcon } from '@/components/ui/Icon'
import { StatusChip, type StatusKind } from '@/components/ui/StatusChip'
import { TargetsEditor } from '@/components/planning/TargetsEditor'
import { Tip } from '@/components/ui/Tip'
import { useHoldings } from '@/hooks/usePortfolio'
import { useCreatePortfolioRule, useDeletePortfolioRule, usePortfolioRules } from '@/hooks/usePlanning'
import { apiErrorMessage } from '@/lib/apiError'
import { BUCKET_LABELS, DIMENSION_LABELS, bucketLabel } from '@/lib/exposures'
import { formatAmount, formatPercent, toNumber } from '@/lib/format'
import type { ExposureDimension, PortfolioRuleCreatePayload, PortfolioRuleKind, PortfolioRuleStatus, RuleState } from '@/types'

const STATE: Record<RuleState, { kind: StatusKind; label: string }> = {
  ok: { kind: 'good', label: 'Nei limiti' },
  over: { kind: 'over', label: 'Sopra' },
  under: { kind: 'over', label: 'Sotto' },
  unknown: { kind: 'ok', label: 'Non valutabile' },
}

const REASONS: Record<string, string> = {
  coverage: 'meno del 90% classificato: completa la Composizione nel Portafoglio',
  no_history: 'serve almeno un mese completo di spese',
  nothing_invested: 'ancora nessun investimento di lungo periodo',
}

const KIND_LABELS: Record<PortfolioRuleKind, string> = {
  target: 'Target',
  max_share: 'Limite massimo',
  excess_cash: 'Liquidità ferma',
  min_invested: 'Quota investita minima',
}

function describe(status: PortfolioRuleStatus, currency: string): { title: string; detail: string } {
  const r = status.rule
  const dim = (r.dimension ?? 'asset_class') as ExposureDimension
  const name = r.dimension === 'position' ? (status.label ?? 'Titolo') : r.bucket ? bucketLabel(dim, r.bucket) : ''
  const now = status.actual_pct !== null ? `ora ${formatPercent(status.actual_pct)}` : ''
  switch (r.kind) {
    case 'target':
      return { title: `${name} ${formatPercent(toNumber(r.target_pct), { digits: 0 })} ± ${toNumber(r.tolerance_pct)}`, detail: now }
    case 'max_share':
      return { title: `${name} al massimo ${formatPercent(toNumber(r.max_pct), { digits: 0 })}`, detail: now }
    case 'excess_cash':
      return {
        title: r.threshold_amount ? `Liquidità ferma oltre ${formatAmount(r.threshold_amount, currency)} ${currency}` : `Liquidità ferma oltre ${toNumber(r.threshold_months)} mesi di spese`,
        detail: status.actual_amount !== null ? `ora ${formatAmount(status.actual_amount, currency)} su ${formatAmount(status.limit_amount, currency)} ${currency}` : '',
      }
    case 'min_invested':
      return { title: `Investito almeno il ${formatPercent(toNumber(r.min_pct), { digits: 0 })} del patrimonio libero`, detail: now }
  }
}

function RuleForm({ onDone }: { onDone: () => void }) {
  const create = useCreatePortfolioRule()
  const { data: holdings } = useHoldings()
  const [kind, setKind] = useState<PortfolioRuleKind>('max_share')
  const [dimension, setDimension] = useState<string>('region')
  const [bucket, setBucket] = useState('')
  const [pctValue, setPctValue] = useState('')
  const [tolerance, setTolerance] = useState('5')
  const [byMonths, setByMonths] = useState(true)
  const [threshold, setThreshold] = useState('6')
  const [error, setError] = useState<string | null>(null)

  const dimensions = kind === 'target' ? ['asset_class', 'region'] : ['asset_class', 'region', 'sector', 'currency', 'position']
  const buckets: [string, string][] =
    dimension === 'position'
      ? [...new Map((holdings ?? []).map((h) => [h.asset.id, h.asset.symbol])).entries()]
      : Object.entries(BUCKET_LABELS[dimension as ExposureDimension] ?? {})

  async function submit() {
    setError(null)
    const num = (v: string) => v.replace(',', '.')
    const payload: PortfolioRuleCreatePayload =
      kind === 'target'
        ? { kind, dimension, bucket, target_pct: num(pctValue), tolerance_pct: num(tolerance) }
        : kind === 'max_share'
          ? { kind, dimension, bucket, max_pct: num(pctValue) }
          : kind === 'excess_cash'
            ? byMonths
              ? { kind, threshold_months: num(threshold) }
              : { kind, threshold_amount: num(threshold) }
            : { kind, min_pct: num(pctValue) }
    try {
      await create.mutateAsync(payload)
      onDone()
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare il paletto.'))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Tipo" htmlFor="rule-kind">
          <select
            id="rule-kind"
            className="field"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as PortfolioRuleKind)
              setDimension(e.target.value === 'target' ? 'asset_class' : 'region')
              setBucket('')
            }}
          >
            {/* Targets are set with the sliders (TargetsEditor), as a whole mix. */}
            {(Object.keys(KIND_LABELS) as PortfolioRuleKind[]).filter((k) => k !== 'target').map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </Field>
        {(kind === 'target' || kind === 'max_share') && (
          <>
            <Field label="Su" htmlFor="rule-dimension">
              <select
                id="rule-dimension"
                className="field"
                value={dimension}
                onChange={(e) => {
                  setDimension(e.target.value)
                  setBucket('')
                }}
              >
                {dimensions.map((d) => (
                  <option key={d} value={d}>
                    {d === 'position' ? 'Singolo titolo' : DIMENSION_LABELS[d as ExposureDimension]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Voce" htmlFor="rule-bucket">
              <select id="rule-bucket" className="field" value={bucket} onChange={(e) => setBucket(e.target.value)}>
                <option value="">Scegli…</option>
                {buckets.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
          </>
        )}
        {kind !== 'excess_cash' && (
          <Field label={kind === 'target' ? 'Target %' : kind === 'max_share' ? 'Massimo %' : 'Minimo %'} htmlFor="rule-pct">
            <input id="rule-pct" inputMode="decimal" className="field" value={pctValue} onChange={(e) => setPctValue(e.target.value)} />
          </Field>
        )}
        {kind === 'target' && (
          <Field label="Tolleranza (punti)" htmlFor="rule-tolerance" hint="Avvisa solo fuori da target ± tolleranza.">
            <input id="rule-tolerance" inputMode="decimal" className="field" value={tolerance} onChange={(e) => setTolerance(e.target.value)} />
          </Field>
        )}
        {kind === 'excess_cash' && (
          <>
            <Field label="Soglia in" htmlFor="rule-threshold-mode">
              <select id="rule-threshold-mode" className="field" value={byMonths ? 'months' : 'amount'} onChange={(e) => setByMonths(e.target.value === 'months')}>
                <option value="months">Mesi di spese medie</option>
                <option value="amount">Importo</option>
              </select>
            </Field>
            <Field label={byMonths ? 'Mesi' : 'Importo'} htmlFor="rule-threshold">
              <input id="rule-threshold" inputMode="decimal" className="field" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
            </Field>
          </>
        )}
      </div>
      <p className="text-[12px] text-ink-3">
        Solo sugli investimenti di lungo periodo{' '}
        <Tip>I paletti valgono solo per gli investimenti di lungo periodo: fondo emergenza, accantonamenti con scadenza e tasse restano fuori.</Tip>
      </p>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>Annulla</Button>
        <Button variant="primary" onClick={submit} disabled={create.isPending}>
          Salva
        </Button>
      </div>
    </div>
  )
}

/** Pillar 4's guardrails: targets, caps, idle cash, and how to split new money. */
export function InvestingRulesSection({ currency }: { currency: string }) {
  const { data, isLoading, isError } = usePortfolioRules()
  const remove = useDeletePortfolioRule()
  const [adding, setAdding] = useState(false)
  const [picking, setPicking] = useState(false)
  const [deleting, setDeleting] = useState<PortfolioRuleStatus | null>(null)

  return (
    <Card
      title="Paletti sugli investimenti"
      meta={<Tip>I limiti che ti dai sul quarto pilastro. Quando ne esci, il banner te lo segnala una volta al mese.</Tip>}
      action={
        <div className="flex gap-2">
          <Button onClick={() => setPicking(true)}>Target…</Button>
          <Button variant="secondary" onClick={() => setAdding(true)}>
            + Paletto
          </Button>
        </div>
      }
    >
      {isLoading ? (
        <LoadingBlock className="mt-3 h-32" />
      ) : isError || !data ? (
        <div className="mt-3">
          <ErrorBlock>Non è stato possibile valutare i paletti.</ErrorBlock>
        </div>
      ) : (
        <>
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px] tabular-nums">
            <div className="flex gap-1.5">
              <dt className="text-ink-2">Investito</dt>
              <dd className="font-extrabold">
                {formatAmount(data.invested, currency)} <span className="ccy">{currency}</span>
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="flex items-center text-ink-2">
                Liquidità ferma
                <Tip label="Cos’è la liquidità ferma" className="-my-2">
                  Quello che sui conti supera le spese del mese, il fondo emergenza mancante e gli addebiti programmati.
                </Tip>
              </dt>
              <dd className="font-extrabold">{data.idle_cash === null ? '—' : `${formatAmount(data.idle_cash, currency)} ${currency}`}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-ink-2">Quota investita</dt>
              <dd className="font-extrabold">{data.invested_share === null ? '—' : formatPercent(data.invested_share)}</dd>
            </div>
          </dl>

          {data.rules.length === 0 ? (
            <div className="mt-3">
              <EmptyState title="Nessun paletto" action={<Button onClick={() => setPicking(true)}>Imposta i target</Button>}>
                Parti da un modello (60/40, tutto il mondo…) e aggiustalo con i cursori, poi aggiungi limiti e soglie con «+ Paletto».
              </EmptyState>
            </div>
          ) : (
            <ul className="mt-3">
              {data.rules.map((status) => {
                const { title, detail } = describe(status, currency)
                const state = STATE[status.state]
                return (
                  <li key={status.rule.id} className="flex items-center justify-between gap-3 border-t border-line py-2 first:border-t-0">
                    <span className="min-w-0 text-[13px]">
                      <span className="font-bold">{title}</span>
                      <span className="block text-ink-2">{status.state === 'unknown' && status.reason ? REASONS[status.reason] : detail}</span>
                    </span>
                    <span className="flex flex-none items-center gap-1">
                      <StatusChip kind={state.kind}>{state.label}</StatusChip>
                      <button
                        type="button"
                        aria-label="Elimina il paletto"
                        onClick={() => setDeleting(status)}
                        className="grid h-11 w-11 cursor-pointer place-items-center rounded-[10px] text-ink-2 hover:bg-card-2"
                      >
                        <CloseIcon />
                      </button>
                    </span>
                  </li>
                )
              })}
            </ul>
          )}

          {data.contribution_split.length > 0 && (
            <div className="mt-3 rounded-[10px] bg-card-2 px-3 py-2 text-[13px]">
              <b>Questo mese, {formatAmount(data.contribution, currency)} {currency} verso gli investimenti:</b>{' '}
              {data.contribution_split.map((s) => `${bucketLabel('asset_class', s.bucket)} ${formatAmount(s.amount, currency)}`).join(' · ')}.
              <span className="block text-ink-3">Per avvicinarsi ai target usando solo i nuovi versamenti, senza vendere (e senza tasse sulle plusvalenze).</span>
            </div>
          )}
        </>
      )}

      <Dialog open={adding} onClose={() => setAdding(false)} title="Nuovo paletto" size="md">
        {adding && <RuleForm onDone={() => setAdding(false)} />}
      </Dialog>
      <Dialog open={picking} onClose={() => setPicking(false)} title="Target di allocazione" size="lg">
        {picking && <TargetsEditor onDone={() => setPicking(false)} />}
      </Dialog>
      <ConfirmDialog
        open={!!deleting}
        title="Eliminare il paletto?"
        confirmLabel="Elimina"
        pending={remove.isPending}
        error={null}
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.rule.id)
          setDeleting(null)
        }}
        onCancel={() => setDeleting(null)}
      >
        {deleting && describe(deleting, currency).title}
      </ConfirmDialog>
    </Card>
  )
}
