import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { CategorySelect } from '@/components/transactions/CategorySelect'
import { Button } from '@/components/ui/Button'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAccounts } from '@/hooks/useAccounts'
import { useCategories } from '@/hooks/useCategories'
import { useCreatePhysicalAsset, useUpdatePhysicalAsset } from '@/hooks/usePhysicalAssets'
import { apiErrorMessage } from '@/lib/apiError'
import { CURRENCIES, CURRENCY_NAMES } from '@/lib/currencies'
import { formatQuantity, toISODate } from '@/lib/format'
import {
  DEFAULT_DEPRECIATION_PCT,
  isLocaleNumber,
  METAL_FORM_LABELS,
  METAL_LABELS,
  millesimiToPurity,
  parseLocaleNumber,
  PURITY_PRESETS,
  purityToMillesimi,
  VEHICLE_TYPE_LABELS,
} from '@/lib/physicalAssets'
import type { MetalForm, PhysicalAssetKind, PhysicalAssetWithValue, PreciousMetal, VehicleType } from '@/types'

const CUSTOM_PURITY = 'custom'

const schema = z
  .object({
    // An edited metal keeps its weight and prices in its movements, so
    // those fields are neither shown nor validated.
    editing: z.boolean(),
    kind: z.enum(['vehicle', 'metal']),
    name: z.string().trim().min(1, 'Il nome è obbligatorio').max(100, 'Massimo 100 caratteri'),
    currency: z.enum(CURRENCIES),
    purchase_date: z.string().min(1, 'Data obbligatoria'),
    purchase_price: z.string(),
    account_id: z.string(),
    category_id: z.string(),
    notes: z.string().max(500, 'Massimo 500 caratteri'),
    vehicle_type: z.enum(['car', 'motorcycle', 'other']),
    depreciation_pct: z.string(),
    metal: z.enum(['gold', 'silver', 'platinum']),
    metal_form: z.enum(['bullion', 'coin', 'jewelry']),
    weight_grams: z.string(),
    purity_preset: z.string(),
    purity_custom: z.string(),
  })
  .superRefine((v, ctx) => {
    const issue = (path: string, message: string) => ctx.addIssue({ code: 'custom', path: [path], message })
    if (v.purchase_price && !(isLocaleNumber(v.purchase_price) && Number(parseLocaleNumber(v.purchase_price)) >= 0)) {
      issue('purchase_price', 'Inserisci un importo valido')
    }
    if (v.account_id && !v.purchase_price) issue('purchase_price', 'Serve un prezzo per pagarlo da un conto')
    if (v.kind === 'vehicle') {
      if (!v.purchase_price) issue('purchase_price', 'Il prezzo è il punto di partenza della svalutazione')
      const pct = Number(parseLocaleNumber(v.depreciation_pct))
      if (!isLocaleNumber(v.depreciation_pct) || pct < 0 || pct >= 100) issue('depreciation_pct', 'Tra 0 e 99')
    } else {
      if (!v.editing && (!isLocaleNumber(v.weight_grams) || Number(parseLocaleNumber(v.weight_grams)) <= 0)) issue('weight_grams', 'Inserisci un peso maggiore di zero')
      if (v.purity_preset === CUSTOM_PURITY) {
        const m = Number(parseLocaleNumber(v.purity_custom))
        if (!isLocaleNumber(v.purity_custom) || m <= 0 || m > 1000) issue('purity_custom', 'Millesimi tra 1 e 1000')
      }
    }
  })

type FormValues = z.infer<typeof schema>

function defaults(asset: PhysicalAssetWithValue | null, kind: PhysicalAssetKind, baseCurrency: string): FormValues {
  const currency = (CURRENCIES as readonly string[]).includes(asset?.currency ?? baseCurrency)
    ? ((asset?.currency ?? baseCurrency) as FormValues['currency'])
    : 'EUR'
  const metal = asset?.metal ?? 'gold'
  const millesimi = asset?.purity ? purityToMillesimi(asset.purity) : PURITY_PRESETS[metal][0].value
  const preset = PURITY_PRESETS[metal].some((p) => p.value === millesimi) ? millesimi : CUSTOM_PURITY
  return {
    editing: asset !== null,
    kind: asset?.kind ?? kind,
    name: asset?.name ?? '',
    currency,
    purchase_date: asset?.purchase_date ?? toISODate(new Date()),
    // A metal's own price is per movement; on edit it isn't shown.
    purchase_price: asset?.purchase_price ?? '',
    account_id: '',
    category_id: '',
    notes: asset?.notes ?? '',
    vehicle_type: asset?.vehicle_type ?? 'car',
    depreciation_pct: asset?.depreciation_rate ? String(Number(asset.depreciation_rate) * 100) : DEFAULT_DEPRECIATION_PCT,
    metal,
    metal_form: asset?.metal_form ?? 'bullion',
    weight_grams: asset?.weight_grams ? String(Number(asset.weight_grams)) : '',
    purity_preset: preset,
    purity_custom: preset === CUSTOM_PURITY ? millesimi : '',
  }
}

/**
 * Create (asset = null) or edit. On edit the kind, metal and currency are
 * fixed — the backend refuses to change them — and the paying account is
 * fixed too: its cash leg follows the price and date automatically.
 */
export function PhysicalAssetForm({
  asset,
  initialKind = 'vehicle',
  baseCurrency,
  onDone,
}: {
  asset: PhysicalAssetWithValue | null
  initialKind?: PhysicalAssetKind
  baseCurrency: string
  onDone: () => void
}) {
  const editing = asset !== null
  // A metal position's weight, prices and dates are its movements.
  const metalEdit = editing && asset.kind === 'metal'
  const createAsset = useCreatePhysicalAsset()
  const updateAsset = useUpdatePhysicalAsset()
  const { data: accounts } = useAccounts()
  const { data: categories } = useCategories()
  const [serverError, setServerError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    control,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: defaults(asset, initialKind, baseCurrency) })

  const kind = useWatch({ control, name: 'kind' })
  const metal = useWatch({ control, name: 'metal' })
  const currency = useWatch({ control, name: 'currency' })
  const accountId = useWatch({ control, name: 'account_id' })
  const purityPreset = useWatch({ control, name: 'purity_preset' })
  const payingAccounts = (accounts ?? []).filter((a) => a.currency === currency && !a.closed_at)

  async function onSubmit(v: FormValues) {
    setServerError(null)
    const price = v.purchase_price ? parseLocaleNumber(v.purchase_price) : null
    const kindFields =
      v.kind === 'vehicle'
        ? {
            vehicle_type: v.vehicle_type as VehicleType,
            depreciation_rate: (Number(parseLocaleNumber(v.depreciation_pct)) / 100).toFixed(4),
          }
        : {
            metal_form: v.metal_form as MetalForm,
            purity: millesimiToPurity(v.purity_preset === CUSTOM_PURITY ? v.purity_custom : v.purity_preset),
          }
    try {
      if (editing) {
        const purchase = v.kind === 'vehicle' ? { purchase_date: v.purchase_date, purchase_price: price } : {}
        await updateAsset.mutateAsync({
          id: asset.id,
          payload: { name: v.name.trim(), notes: v.notes.trim() || null, ...purchase, ...kindFields },
        })
      } else {
        await createAsset.mutateAsync({
          kind: v.kind,
          name: v.name.trim(),
          notes: v.notes.trim() || null,
          currency: v.currency,
          purchase_date: v.purchase_date,
          purchase_price: price,
          account_id: v.account_id || null,
          category_id: v.account_id && v.category_id ? v.category_id : null,
          ...kindFields,
          ...(v.kind === 'metal' ? { metal: v.metal as PreciousMetal, weight_grams: parseLocaleNumber(v.weight_grams) } : {}),
        })
      }
      onDone()
    } catch (error) {
      setServerError(apiErrorMessage(error, 'Impossibile salvare il bene. Riprova.'))
    }
  }

  const fieldProps = (name: keyof FormValues, id: string) => ({
    id,
    'aria-invalid': !!errors[name],
    'aria-describedby': errors[name] ? `${id}-msg` : undefined,
  })

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
      {!editing && (
        <SegmentedControl
          label="Tipo di bene"
          options={[
            { value: 'vehicle', label: 'Veicolo' },
            { value: 'metal', label: 'Metallo prezioso' },
          ]}
          value={kind}
          onChange={(next) => setValue('kind', next)}
        />
      )}

      <Field label="Nome" htmlFor="pa-name" error={errors.name?.message}>
        <input
          className="field"
          placeholder={kind === 'vehicle' ? 'Es. Fiat Panda 2021' : 'Es. Lingotto 100 g, Fede nuziale'}
          {...fieldProps('name', 'pa-name')}
          {...register('name')}
        />
      </Field>

      {kind === 'vehicle' ? (
        <div className="grid grid-cols-2 gap-2.5">
          <Field label="Tipo" htmlFor="pa-vtype">
            <select id="pa-vtype" className="field" {...register('vehicle_type')}>
              {Object.entries(VEHICLE_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Svalutazione annua" htmlFor="pa-dep" error={errors.depreciation_pct?.message}>
            <div className="relative">
              <input inputMode="decimal" className="field pr-8 tabular-nums" {...fieldProps('depreciation_pct', 'pa-dep')} {...register('depreciation_pct')} />
              <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">%</span>
            </div>
          </Field>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Metallo" htmlFor="pa-metal">
              {/* Shown, not disabled, on edit: a disabled input drops out of
                  the submitted values and would fail validation. */}
              {editing ? (
                <div id="pa-metal" className="field flex items-center text-ink-2">
                  {METAL_LABELS[metal]}
                </div>
              ) : (
                <select
                  id="pa-metal"
                  className="field"
                  {...register('metal', {
                    onChange: (e) => setValue('purity_preset', PURITY_PRESETS[e.target.value as PreciousMetal][0].value),
                  })}
                >
                  {Object.entries(METAL_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Forma" htmlFor="pa-form">
              <select id="pa-form" className="field" {...register('metal_form')}>
                {Object.entries(METAL_FORM_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-2.5">
            <Field label={metalEdit ? 'Peso posseduto' : 'Peso'} htmlFor="pa-weight" error={errors.weight_grams?.message}>
              {metalEdit ? (
                <div id="pa-weight" className="field flex items-center text-ink-2 tabular-nums">
                  {formatQuantity(asset.weight_grams ?? 0)} g
                </div>
              ) : (
                <div className="relative">
                  <input inputMode="decimal" placeholder="0,00" className="field pr-8 tabular-nums" {...fieldProps('weight_grams', 'pa-weight')} {...register('weight_grams')} />
                  <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">g</span>
                </div>
              )}
            </Field>
            <Field label="Purezza" htmlFor="pa-purity">
              <select id="pa-purity" className="field" {...register('purity_preset')}>
                {PURITY_PRESETS[metal].map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
                <option value={CUSTOM_PURITY}>Altro…</option>
              </select>
            </Field>
          </div>
          {purityPreset === CUSTOM_PURITY && (
            <Field label="Titolo in millesimi" htmlFor="pa-purity-custom" error={errors.purity_custom?.message} hint="Il numero punzonato sull'oggetto, es. 750.">
              <input inputMode="decimal" className="field tabular-nums" {...fieldProps('purity_custom', 'pa-purity-custom')} {...register('purity_custom')} />
            </Field>
          )}
          <p className="-mt-1 text-[12px] text-ink-3">
            Il valore è quello del metallo fino alla quotazione di oggi. Per i gioielli è una stima prudente: la lavorazione non si
            rivende.
          </p>
        </>
      )}

      <div className="grid grid-cols-[110px_1fr] gap-2.5">
        <Field label="Valuta" htmlFor="pa-ccy">
          {editing ? (
            <div id="pa-ccy" className="field flex items-center text-ink-2">
              {currency}
            </div>
          ) : (
            <select id="pa-ccy" className="field" {...register('currency', { onChange: () => setValue('account_id', '') })}>
              {CURRENCIES.map((c) => (
                <option key={c} value={c} title={CURRENCY_NAMES[c]}>
                  {c}
                </option>
              ))}
            </select>
          )}
        </Field>
        {!metalEdit && (
          <Field
            label={kind === 'vehicle' ? 'Prezzo di acquisto' : 'Prezzo di acquisto (facoltativo)'}
            htmlFor="pa-price"
            error={errors.purchase_price?.message}
            hint={kind === 'metal' ? 'Lascialo vuoto per un bene ereditato o regalato.' : undefined}
          >
            <input inputMode="decimal" placeholder="0,00" className="field tabular-nums" {...fieldProps('purchase_price', 'pa-price')} {...register('purchase_price')} />
          </Field>
        )}
      </div>

      {metalEdit ? (
        <p className="-mt-1 text-[12px] text-ink-3">Peso, prezzi e date si cambiano da «Acquista o vendi»: ogni acquisto e vendita è un movimento.</p>
      ) : (
        <Field label="Data di acquisto" htmlFor="pa-date" error={errors.purchase_date?.message}>
          <input type="date" className="field" {...fieldProps('purchase_date', 'pa-date')} {...register('purchase_date')} />
        </Field>
      )}

      {!editing && (
        <>
          <Field label="Pagato da" htmlFor="pa-account" hint="Facoltativo: registra l'uscita come giroconto, così la liquidità scende e il patrimonio non conta due volte.">
            <select id="pa-account" className="field" {...register('account_id')}>
              <option value="">Nessun conto (lo possiedo già)</option>
              {payingAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
          {accountId && (
            <Field label="Categoria del giroconto" htmlFor="pa-category">
              <CategorySelect id="pa-category" categories={categories} type="transfer" emptyLabel="Nessuna categoria" {...register('category_id')} />
            </Field>
          )}
        </>
      )}

      <Field label="Note" htmlFor="pa-notes" error={errors.notes?.message}>
        <textarea rows={2} className="field" {...fieldProps('notes', 'pa-notes')} {...register('notes')} />
      </Field>

      {serverError && <ErrorBlock>{serverError}</ErrorBlock>}
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>Annulla</Button>
        <Button type="submit" variant="primary" disabled={isSubmitting}>
          {isSubmitting ? 'Salvataggio…' : editing ? 'Salva' : 'Aggiungi bene'}
        </Button>
      </div>
    </form>
  )
}
