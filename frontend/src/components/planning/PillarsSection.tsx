import { useState } from 'react'
import { Card } from '@/components/ui/Card'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorBlock, LoadingBlock, Notice } from '@/components/ui/EmptyState'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { StatusChip } from '@/components/ui/StatusChip'
import { GoalSchedule } from '@/components/planning/GoalSchedule'
import { Tip } from '@/components/ui/Tip'
import { usePlan, useUpdatePlan } from '@/hooks/usePlanning'
import { usePillars } from '@/hooks/useSavingsGoals'
import { formatAmount, formatShortDate, toNumber } from '@/lib/format'
import type { Pillar, PillarItem, PillarKey } from '@/types'

const PILLARS: Record<PillarKey, { title: string; blurb: string }> = {
  operating: { title: 'Liquidità', blurb: 'I conti per le spese del mese, non assegnati a obiettivi.' },
  emergency: { title: 'Fondo emergenza', blurb: 'La riserva per gli imprevisti: si riempie per prima.' },
  planned: { title: 'Accantonamenti', blurb: 'Spese con una data o già note: auto, casa, tasse, scadenze.' },
  investing: { title: 'Investimenti', blurb: 'Il lungo periodo: quello che non serve nei prossimi anni.' },
}

const MONTH_CHOICES = ['0.5', '1', '2', '3']

function money(value: string | null, currency: string) {
  return `${formatAmount(value, currency)} ${currency}`
}

function ItemRow({ item }: { item: PillarItem }) {
  const detail =
    item.kind === 'vehicle_deadline' && item.due_date
      ? `${money(item.amount, item.currency)} entro il ${formatShortDate(item.due_date)} · ${money(item.monthly, item.currency)}/mese`
      : item.kind === 'tax_provision'
        ? `${money(item.available, item.currency)} su ${money(item.amount, item.currency)} che chiederanno gli F24`
        : money(item.available, item.currency)
  return (
    <li className="flex flex-col py-1 text-[13px]">
      <span className="font-semibold">{item.label}</span>
      <span className="text-ink-2 tabular-nums">{detail}</span>
    </li>
  )
}

function OperatingMonths({ value }: { value: string }) {
  const { data: plan } = usePlan()
  const updatePlan = useUpdatePlan()
  const current = String(Number(plan?.operating_cash_months ?? value))
  return (
    <label className="mt-1 flex items-center gap-2 text-[13px] text-ink-2">
      Obiettivo
      <select
        className="field h-9 w-auto py-0"
        value={current}
        disabled={updatePlan.isPending}
        onChange={(e) => updatePlan.mutate({ operating_cash_months: e.target.value })}
      >
        {MONTH_CHOICES.map((m) => (
          <option key={m} value={m}>
            {m.replace('.', ',')} {m === '1' ? 'mese' : 'mesi'}
          </option>
        ))}
      </select>
      di spese medie
    </label>
  )
}

function PillarNumbers({ pillar, currency }: { pillar: Pillar; currency: string }) {
  const meta = PILLARS[pillar.key]
  const target = pillar.target === null ? null : toNumber(pillar.target)
  const pct = target ? Math.min(100, (toNumber(pillar.current) / target) * 100) : null
  const full = target !== null && toNumber(pillar.gap) <= 0
  return (
    <>
      <p className="mt-2 text-[20px] font-extrabold tabular-nums">
        {formatAmount(pillar.current, currency)} <span className="ccy text-[13px]">{currency}</span>
      </p>
      {target !== null ? (
        <>
          <p className="text-[13px] text-ink-2 tabular-nums">
            su {money(pillar.target, currency)}
            {!full && <> · mancano {money(pillar.gap, currency)}</>}
          </p>
          <div className="mt-1.5">
            <ProgressBar value={pct ?? 0} kind={full ? 'good' : 'ok'} label={`${meta.title}: ${Math.round(pct ?? 0)}%`} />
          </div>
        </>
      ) : pillar.key === 'operating' ? (
        <p className="text-[13px] text-warn">Obiettivo da calcolare: serve un mese completo di spese.</p>
      ) : pillar.key === 'investing' ? (
        <p className="text-[13px] text-ink-2">Senza tetto: è dove va ciò che avanza.</p>
      ) : (
        <p className="text-[13px] text-ink-3">Nessun obiettivo.</p>
      )}
      {pillar.monthly_required !== null && toNumber(pillar.monthly_required) > 0 && (
        <p className="mt-1 text-[13px] font-semibold tabular-nums">{money(pillar.monthly_required, currency)} al mese da mettere da parte</p>
      )}
    </>
  )
}

function PillarDetails({ pillar, currency, months, monthlySpend }: { pillar: Pillar; currency: string; months: string; monthlySpend: string | null }) {
  return (
    <div className="flex flex-col gap-3">
      <div>
        <PillarNumbers pillar={pillar} currency={currency} />
      </div>

      {pillar.key === 'operating' && (
        <div>
          <OperatingMonths value={months} />
          {monthlySpend !== null && <p className="text-[12px] text-ink-3 tabular-nums">Spesa media: {money(monthlySpend, currency)} al mese</p>}
        </div>
      )}

      {pillar.steps.length > 0 && (
        <section aria-label="Obiettivi">
          <h3 className="text-[13px] font-extrabold text-ink-2">Obiettivi</h3>
          <ul className="mt-1">
            {pillar.steps.map((step) => (
              <li key={step.goal_id} className="border-t border-line py-2 text-[13px] first:border-t-0">
                <span className="flex justify-between gap-2">
                  <span className="font-semibold">{step.name}</span>
                  <span className="text-ink-2 tabular-nums">
                    {step.target_amount === null
                      ? money(step.current_amount, currency)
                      : `${formatAmount(step.current_amount, currency)} su ${money(step.target_amount, currency)} · ${Math.round(step.funding_percentage)}%`}
                  </span>
                </span>
                <GoalSchedule step={step} currency={currency} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {pillar.items.length > 0 && (
        <section aria-label={pillar.key === 'investing' ? 'Composizione' : 'Altre voci'}>
          <h3 className="text-[13px] font-extrabold text-ink-2">
            {pillar.key === 'investing'
              ? 'Cosa c’è dentro'
              : pillar.key === 'operating'
                ? 'Eccedenza sui conti degli obiettivi (obiettivi già pieni): la cascata la sposta'
                : 'Già messo da parte o in arrivo'}
          </h3>
          <ul className="mt-1">
            {pillar.items.map((item) => (
              <ItemRow key={`${item.kind}-${item.label}`} item={item} />
            ))}
          </ul>
        </section>
      )}

      {pillar.steps.length === 0 && pillar.items.length === 0 && pillar.key !== 'operating' && (
        <p className="text-[13px] text-ink-3">Nessun obiettivo in questo pilastro: aggiungine uno dalla cascata del risparmio qui sotto.</p>
      )}
    </div>
  )
}

function PillarTile({ pillar, index, currency, onOpen }: { pillar: Pillar; index: number; currency: string; onOpen: () => void }) {
  const meta = PILLARS[pillar.key]
  const full = pillar.target !== null && toNumber(pillar.gap) <= 0
  const behind = pillar.steps.filter((s) => s.on_track === false).length
  const extra = pillar.steps.length + pillar.items.length

  return (
    <div className="flex min-w-0 flex-col rounded-[12px] border border-line bg-card-2/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[14px] font-extrabold">
          <span className="text-ink-3">{index + 1}</span> {meta.title}
        </h3>
        {full ? <StatusChip kind="good">Coperto</StatusChip> : behind > 0 ? <StatusChip kind="over">{behind} in ritardo</StatusChip> : null}
      </div>
      <PillarNumbers pillar={pillar} currency={currency} />
      <button
        type="button"
        onClick={onOpen}
        className="mt-auto self-start pt-2 text-[13px] font-bold text-accent hover:underline"
        aria-label={`Dettagli di ${meta.title}`}
      >
        Dettagli{extra > 0 ? ` · ${extra} ${extra === 1 ? 'voce' : 'voci'}` : ''} →
      </button>
    </div>
  )
}

/**
 * The four pillars of the plan, in the order money should fill them. A
 * reading of where the money is against what each layer needs; the cascade
 * below is where the month's quota gets moved.
 */
export function PillarsSection({ date }: { date: string }) {
  const { data, isLoading, isError } = usePillars(date)
  // The key, not the object: the dialog then shows the fresh pillar after a
  // refetch (changing the operating months from inside it, for one).
  const [open, setOpen] = useState<PillarKey | null>(null)
  const openPillar = data?.pillars.find((p) => p.key === open) ?? null

  return (
    <Card
      title="I quattro pilastri"
      meta={
        <Tip>
          Prima la liquidità per il mese, poi il fondo emergenza, poi gli accantonamenti per le spese con una data, e solo dopo gli investimenti.
        </Tip>
      }
    >
      {isLoading ? (
        <LoadingBlock className="mt-3 h-48" />
      ) : isError || !data ? (
        <div className="mt-3">
          <ErrorBlock>Non è stato possibile calcolare i pilastri.</ErrorBlock>
        </div>
      ) : (
        <>
          {data.has_unpriced_holdings && (
            <div className="mt-3">
              <Notice>Alcuni investimenti non hanno ancora un prezzo salvato e non sono contati: apri il Portafoglio per aggiornarli.</Notice>
            </div>
          )}
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {data.pillars.map((pillar, i) => (
              <PillarTile key={pillar.key} pillar={pillar} index={i} currency={data.base_currency} onOpen={() => setOpen(pillar.key)} />
            ))}
          </div>
          <Dialog
            open={openPillar !== null}
            onClose={() => setOpen(null)}
            title={openPillar ? `${data.pillars.indexOf(openPillar) + 1} · ${PILLARS[openPillar.key].title}` : ''}
            description={openPillar ? PILLARS[openPillar.key].blurb : undefined}
            size="md"
          >
            {openPillar && (
              <PillarDetails pillar={openPillar} currency={data.base_currency} months={data.operating_cash_months} monthlySpend={data.monthly_total_expenses} />
            )}
          </Dialog>
        </>
      )}
    </Card>
  )
}
