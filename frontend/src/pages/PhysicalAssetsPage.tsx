import { useState, type ComponentType, type SVGProps } from 'react'
import { PhysicalAssetForm } from '@/components/physical-assets/PhysicalAssetForm'
import { SellDialog, ValuationsDialog } from '@/components/physical-assets/PhysicalAssetDialogs'
import { Delta } from '@/components/ui/Amount'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog, Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { GemIcon } from '@/components/ui/Icon'
import { KpiStrip, type Kpi } from '@/components/ui/KpiStrip'
import { PageHeader } from '@/components/ui/PageHeader'
import { RowMenu, type RowMenuItem } from '@/components/ui/RowMenu'
import { StatusChip } from '@/components/ui/StatusChip'
import { useAuth } from '@/hooks/useAuth'
import { useDeletePhysicalAsset, usePhysicalAssets, useUnsellPhysicalAsset } from '@/hooks/usePhysicalAssets'
import { apiErrorMessage } from '@/lib/apiError'
import { formatAmount, formatFullDate, formatPercent, formatQuantity, toNumber } from '@/lib/format'
import { METAL_FORM_LABELS, METAL_LABELS, purityToMillesimi, VEHICLE_TYPE_LABELS } from '@/lib/physicalAssets'
import type { PhysicalAssetKind, PhysicalAssetWithValue, PreciousMetal } from '@/types'

function CarIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M5 17H3v-5l2-5h14l2 5v5h-2M5 12h14" />
      <circle cx="7.5" cy="17" r="2" />
      <circle cx="16.5" cy="17" r="2" />
    </svg>
  )
}

type FormState = { asset: PhysicalAssetWithValue | null; kind: PhysicalAssetKind } | null

function AssetRow({
  asset,
  base,
  icon: Icon,
  detail,
  actions,
}: {
  asset: PhysicalAssetWithValue
  base: string
  icon: ComponentType<SVGProps<SVGSVGElement>>
  detail: string
  actions: RowMenuItem[]
}) {
  const sold = asset.sold_at !== null
  const value = sold ? asset.sale_price_base_currency : asset.current_value_base_currency
  const cost = toNumber(asset.purchase_price_base_currency)
  const pnl = asset.pnl_base_currency === null ? null : toNumber(asset.pnl_base_currency)
  return (
    <li className={`flex items-center gap-3 border-t border-line py-3 tabular-nums ${sold ? 'opacity-70' : ''}`}>
      <span className="grid h-10 w-10 flex-none place-items-center rounded-[10px] bg-card-2 text-ink-2 max-sm:hidden">
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px] font-extrabold">
          <span className="min-w-0 break-words">{asset.name}</span>
          {sold && <StatusChip>Venduto il {formatFullDate(asset.sold_at!)}</StatusChip>}
        </div>
        <div className="text-[12px] text-ink-3">{detail}</div>
      </div>
      <div className="flex-none text-right">
        <div className="text-[16px] font-extrabold whitespace-nowrap">
          {value === null ? (
            <span className="text-ink-3" title="Quotazione non disponibile al momento">
              n.d.
            </span>
          ) : (
            <>
              {formatAmount(value, base)} <span className="ccy">{base}</span>
            </>
          )}
        </div>
        {pnl !== null && (
          <div className="text-[12px] whitespace-nowrap">
            <Delta value={pnl} currency={base} percent={cost ? (pnl / cost) * 100 : null} />
            {sold ? ' realizzato' : ''}
          </div>
        )}
      </div>
      <RowMenu label={`Azioni per ${asset.name}`} items={actions} />
    </li>
  )
}

function vehicleDetail(a: PhysicalAssetWithValue): string {
  const parts = [
    a.vehicle_type ? VEHICLE_TYPE_LABELS[a.vehicle_type] : 'Veicolo',
    `acquistato il ${formatFullDate(a.purchase_date)}`,
    `−${formatPercent(toNumber(a.depreciation_rate) * 100)}/anno`,
  ]
  const last = a.valuations[a.valuations.length - 1]
  if (last) parts.push(`valutato ${formatAmount(last.value, a.currency, { digits: 0 })} ${a.currency} il ${formatFullDate(last.date)}`)
  return parts.join(' · ')
}

function metalDetail(a: PhysicalAssetWithValue): string {
  return [
    `${a.metal ? METAL_LABELS[a.metal] : ''} ${a.metal_form ? METAL_FORM_LABELS[a.metal_form].toLowerCase() : ''}`.trim(),
    `${formatQuantity(a.weight_grams ?? 0)} g`,
    `${a.purity ? purityToMillesimi(a.purity).replace('.', ',') : ''}‰`,
    `${formatQuantity(Number(toNumber(a.fine_weight_grams).toFixed(3)))} g di fino`,
  ].join(' · ')
}

export function PhysicalAssetsPage() {
  const { user } = useAuth()
  const base = user?.base_currency ?? ''
  const [today] = useState(() => new Date())
  const [showSold, setShowSold] = useState(false)
  const { data, isLoading, isError } = usePhysicalAssets(showSold)
  const deleteAsset = useDeletePhysicalAsset()
  const unsell = useUnsellPhysicalAsset()
  const [form, setForm] = useState<FormState>(null)
  const [selling, setSelling] = useState<PhysicalAssetWithValue | null>(null)
  const [valuing, setValuing] = useState<PhysicalAssetWithValue | null>(null)
  const [deleting, setDeleting] = useState<PhysicalAssetWithValue | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const assets = data ?? []
  const held = assets.filter((a) => a.sold_at === null)
  const vehicles = assets.filter((a) => a.kind === 'vehicle')
  const metals = assets.filter((a) => a.kind === 'metal')
  const sumValue = (list: PhysicalAssetWithValue[]) => list.reduce((s, a) => s + toNumber(a.current_value_base_currency), 0)
  const heldVehicles = held.filter((a) => a.kind === 'vehicle')
  const heldMetals = held.filter((a) => a.kind === 'metal')
  const unpriced = held.filter((a) => a.current_value_base_currency === null).length

  // Spot per gram is the same for every object of a metal; take any.
  const spotByMetal = new Map<PreciousMetal, string>()
  for (const a of metals) if (a.metal && a.spot_price_per_gram_base_currency) spotByMetal.set(a.metal, a.spot_price_per_gram_base_currency)

  const kpis: Kpi[] = [
    {
      label: 'Valore dei beni',
      value: (
        <>
          {formatAmount(sumValue(held), base)} <span className="ccy">{base}</span>
        </>
      ),
      sub: unpriced ? `${unpriced} senza quotazione, esclusi dal totale` : `${held.length} ${held.length === 1 ? 'bene' : 'beni'} posseduti`,
      subTone: unpriced ? 'warn' : 'muted',
    },
    {
      label: 'Veicoli',
      value: formatAmount(sumValue(heldVehicles), base),
      sub: `${heldVehicles.length} ${heldVehicles.length === 1 ? 'veicolo' : 'veicoli'} · stima con svalutazione`,
    },
    {
      label: 'Metalli preziosi',
      value: formatAmount(sumValue(heldMetals), base),
      sub: `${heldMetals.length} ${heldMetals.length === 1 ? 'oggetto' : 'oggetti'} · al valore del fino`,
    },
    ...[...spotByMetal.entries()].map(([metal, spot]) => ({
      label: `Quotazione ${METAL_LABELS[metal].toLowerCase()}`,
      value: (
        <>
          {formatAmount(spot, base)} <span className="ccy">{base}/g</span>
        </>
      ),
      sub: 'metallo fino, oggi',
    })),
  ]

  function actionsFor(asset: PhysicalAssetWithValue): RowMenuItem[] {
    const items: RowMenuItem[] = [{ label: 'Modifica', onSelect: () => setForm({ asset, kind: asset.kind }) }]
    if (asset.kind === 'vehicle') items.push({ label: 'Valutazioni', onSelect: () => setValuing(asset) })
    items.push(
      asset.sold_at === null
        ? { label: 'Vendi', onSelect: () => setSelling(asset) }
        : {
            label: 'Annulla vendita',
            onSelect: async () => {
              setActionError(null)
              try {
                await unsell.mutateAsync(asset.id)
              } catch (e) {
                setActionError(apiErrorMessage(e))
              }
            },
          },
      {
        label: 'Elimina',
        tone: 'danger',
        onSelect: () => {
          setActionError(null)
          setDeleting(asset)
        },
      },
    )
    return items
  }

  async function confirmDelete() {
    if (!deleting) return
    try {
      await deleteAsset.mutateAsync(deleting.id)
      setDeleting(null)
    } catch (e) {
      setActionError(apiErrorMessage(e, 'Impossibile eliminare il bene.'))
    }
  }

  const sections = [
    {
      kind: 'vehicle' as const,
      title: 'Veicoli',
      items: vehicles,
      icon: CarIcon,
      detail: vehicleDetail,
      empty: 'Auto, moto e altri veicoli: si svalutano ogni anno, e puoi correggere la stima con una quotazione.',
    },
    {
      kind: 'metal' as const,
      title: 'Metalli preziosi',
      items: metals,
      icon: GemIcon,
      detail: metalDetail,
      empty: 'Lingotti, monete e gioielli in oro, argento o platino, valutati ogni giorno a peso × purezza × quotazione.',
    },
  ]

  return (
    <>
      <PageHeader
        title="Beni"
        subtitle={`Valori al ${formatFullDate(today)} in ${base} · contano nel patrimonio, non nella liquidità`}
        actions={
          <>
            <Button variant="primary" onClick={() => setForm({ asset: null, kind: 'vehicle' })}>
              + Veicolo
            </Button>
            <Button variant="primary" onClick={() => setForm({ asset: null, kind: 'metal' })}>
              + Metallo prezioso
            </Button>
          </>
        }
      />

      <KpiStrip label="Riepilogo beni" items={kpis} />

      <label className="flex min-h-11 w-fit cursor-pointer items-center gap-2 text-[14px] font-semibold text-ink-2">
        <input type="checkbox" className="h-4 w-4" checked={showSold} onChange={(e) => setShowSold(e.target.checked)} />
        Mostra anche i beni venduti
      </label>

      {actionError && deleting === null && <ErrorBlock>{actionError}</ErrorBlock>}

      {isLoading ? (
        <LoadingBlock className="h-64" />
      ) : isError ? (
        <ErrorBlock>Errore nel caricamento dei beni.</ErrorBlock>
      ) : (
        sections.map((section) => (
          <Card
            key={section.kind}
            title={section.title}
            meta={
              section.items.length > 0 && (
                <span className="text-[13px] font-bold text-ink-3 tabular-nums">
                  {formatAmount(sumValue(section.items.filter((a) => a.sold_at === null)), base)} {base}
                </span>
              )
            }
          >
            {section.items.length === 0 ? (
              <div className="mt-3">
                <EmptyState
                  title={section.kind === 'vehicle' ? 'Nessun veicolo' : 'Nessun metallo prezioso'}
                  action={
                    <Button variant="primary" onClick={() => setForm({ asset: null, kind: section.kind })}>
                      {section.kind === 'vehicle' ? 'Aggiungi un veicolo' : 'Aggiungi un metallo prezioso'}
                    </Button>
                  }
                >
                  {section.empty}
                </EmptyState>
              </div>
            ) : (
              <ul className="mt-2">
                {section.items.map((asset) => (
                  <AssetRow key={asset.id} asset={asset} base={base} icon={section.icon} detail={section.detail(asset)} actions={actionsFor(asset)} />
                ))}
              </ul>
            )}
          </Card>
        ))
      )}

      <Dialog
        open={form !== null}
        onClose={() => setForm(null)}
        size="md"
        title={form?.asset ? `Modifica ${form.asset.name}` : 'Nuovo bene'}
        description={form?.asset ? 'Tipo, metallo e valuta restano quelli scelti alla creazione.' : undefined}
      >
        {form && (
          <PhysicalAssetForm
            key={form.asset?.id ?? `new-${form.kind}`}
            asset={form.asset}
            initialKind={form.kind}
            baseCurrency={base}
            onDone={() => setForm(null)}
          />
        )}
      </Dialog>
      <SellDialog asset={selling} onClose={() => setSelling(null)} />
      <ValuationsDialog asset={valuing} onClose={() => setValuing(null)} />
      <ConfirmDialog
        open={deleting !== null}
        title={deleting ? `Eliminare ${deleting.name}?` : ''}
        confirmLabel="Elimina"
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
        pending={deleteAsset.isPending}
        error={actionError}
      >
        Spariscono anche le valutazioni e gli eventuali giroconti di acquisto e vendita. Se l'hai venduto, usa «Vendi» per
        conservarne la storia.
      </ConfirmDialog>
    </>
  )
}
