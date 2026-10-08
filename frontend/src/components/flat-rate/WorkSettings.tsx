import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { YearPicker } from '@/components/flat-rate/YearPicker'
import { Button } from '@/components/ui/Button'
import { ErrorBlock, LoadingBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { CheckIcon } from '@/components/ui/Icon'
import { useAccounts } from '@/hooks/useAccounts'
import { useAuth } from '@/hooks/useAuth'
import {
  useAddProvisionSource,
  useFlatRateSettings,
  useFlatRateYear,
  useProvision,
  useRemoveProvisionSource,
  useUpdateFlatRateSettings,
  useUpdateFlatRateYear,
} from '@/hooks/useFlatRate'
import { useHoldings } from '@/hooks/usePortfolio'
import { apiErrorMessage } from '@/lib/apiError'
import { COEFFICIENTS, isPercentInput, percentInputToRate, rateToPercentInput, TAX_RATES, WORK_TYPE_LABELS } from '@/lib/flatRate'
import { formatAmount, formatPercent, toNumber } from '@/lib/format'
import type { FlatRateYear, WorkType } from '@/types'

function Saved({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="inline-flex items-center gap-1.5 text-[13px] font-bold text-pos">
      <CheckIcon /> {children}
    </p>
  )
}

const AUTO = 'auto'

const WORK_OPTIONS: { value: WorkType | null; label: string; hint: string }[] = [
  { value: null, label: 'Nessuno', hint: 'Sezione disattivata' },
  { value: 'employee', label: WORK_TYPE_LABELS.employee, hint: 'Nessuna sezione dedicata, per ora' },
  { value: 'flat_rate', label: WORK_TYPE_LABELS.flat_rate, hint: 'Fatture, tasse e accantonamento' },
  { value: 'ordinary', label: WORK_TYPE_LABELS.ordinary, hint: 'Nessuna sezione dedicata, per ora' },
]

function PercentInput({ id, value, onChange, invalid }: { id: string; value: string; onChange: (v: string) => void; invalid?: boolean }) {
  return (
    <div className="relative">
      <input
        id={id}
        inputMode="decimal"
        className="field pr-10 tabular-nums"
        aria-invalid={invalid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className="ccy absolute top-1/2 right-3 -translate-y-1/2">%</span>
    </div>
  )
}

/** The "Lavoro" section of the profile: work type, and the P.IVA settings it unlocks. */
export function WorkSettings() {
  const { user, updateProfile } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const current = user?.work_type ?? null

  async function choose(value: WorkType | null) {
    if (value === current) return
    setSaving(true)
    setError(null)
    try {
      await updateProfile({ work_type: value })
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare il tipo di lavoro.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div role="radiogroup" aria-label="Tipo di lavoro" className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2">
        {WORK_OPTIONS.map((option) => {
          const on = option.value === current
          return (
            <button
              key={option.value ?? 'none'}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={saving}
              onClick={() => choose(option.value)}
              className={`flex min-h-14 cursor-pointer flex-col items-start justify-center rounded-[12px] border px-3 py-2 text-left ${
                on ? 'border-accent bg-accent-soft text-accent' : 'border-field bg-card hover:bg-card-2'
              }`}
            >
              <span className="text-[15px] font-extrabold">{option.label}</span>
              <span className={`text-[12px] ${on ? 'text-accent' : 'text-ink-3'}`}>{option.hint}</span>
            </button>
          )
        })}
      </div>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      {current === 'flat_rate' && <FlatRateSettingsPanel />}
    </div>
  )
}

function FlatRateSettingsPanel() {
  return (
    <>
      <p className="text-[14px] text-ink-2">
        I parametri valgono per anno e restano congelati: cambiare quelli del 2027 non ricalcola il 2026. Fatture, scadenze F24 e gap sono nella
        pagina{' '}
        <Link to="/invoices" className="font-bold text-accent underline-offset-2 hover:underline">
          Fatture
        </Link>
        .
      </p>
      <ActivitySettings />
      <YearSettings />
      <ProvisionSources />
    </>
  )
}

function SubHeading({ children }: { children: ReactNode }) {
  return <h3 className="text-[15px] font-extrabold">{children}</h3>
}

function ActivitySettings() {
  const { data: settings, isLoading } = useFlatRateSettings()
  if (isLoading || !settings) return <LoadingBlock className="h-24" />
  return <ActivityForm key={`${settings.activity_start_date}-${settings.safety_margin}`} start={settings.activity_start_date} margin={settings.safety_margin} />
}

function ActivityForm({ start, margin }: { start: string | null; margin: string }) {
  const update = useUpdateFlatRateSettings()
  const [startDate, setStartDate] = useState(start ?? '')
  const [marginInput, setMarginInput] = useState(rateToPercentInput(margin))
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const dirty = startDate !== (start ?? '') || marginInput !== rateToPercentInput(margin)

  async function save() {
    if (!isPercentInput(marginInput)) return setError('Il margine va da 0 a 100')
    setError(null)
    try {
      await update.mutateAsync({ activity_start_date: startDate || null, safety_margin: percentInputToRate(marginInput) })
      setSaved(true)
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare.'))
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <SubHeading>Attività</SubHeading>
      <div className="grid gap-2.5 sm:grid-cols-2">
        <Field label="Inizio attività" htmlFor="fr-start" hint="Serve a capire il primo anno e a quanti mesi rapportare gli acconti.">
          <input
            id="fr-start"
            type="date"
            className="field"
            value={startDate}
            onChange={(e) => {
              setSaved(false)
              setStartDate(e.target.value)
            }}
          />
        </Field>
        <Field label="Margine di sicurezza" htmlFor="fr-margin" hint="Aggiunto al fabbisogno calcolato prima di arrotondare al 5%.">
          <PercentInput
            id="fr-margin"
            value={marginInput}
            onChange={(v) => {
              setSaved(false)
              setMarginInput(v)
            }}
          />
        </Field>
      </div>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={save} disabled={!dirty || update.isPending}>
          {update.isPending ? 'Salvataggio…' : 'Salva attività'}
        </Button>
        {saved && !dirty && <Saved>Salvato</Saved>}
      </div>
    </div>
  )
}

function YearSettings() {
  const [year, setYear] = useState(() => new Date().getFullYear())
  const { data, isLoading } = useFlatRateYear(year)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SubHeading>Parametri fiscali</SubHeading>
        <YearPicker year={year} onChange={setYear} />
      </div>
      {isLoading || !data ? <LoadingBlock className="h-40" /> : <YearForm key={`${data.year}-${JSON.stringify(data)}`} data={data} />}
    </div>
  )
}

function YearForm({ data }: { data: FlatRateYear }) {
  const update = useUpdateFlatRateYear()
  const [coefficient, setCoefficient] = useState(Number(data.profitability_coefficient).toFixed(4))
  // 'auto' = derived from the start date (5% for the first five years).
  const [taxRate, setTaxRate] = useState(data.substitute_tax_rate_is_automatic ? AUTO : Number(data.substitute_tax_rate).toFixed(4))
  const [inps, setInps] = useState(rateToPercentInput(data.inps_rate))
  const [rivalsa, setRivalsa] = useState(toNumber(data.rivalsa_rate) > 0)
  const [custom, setCustom] = useState(data.provision_rate !== null)
  const [provision, setProvision] = useState(rateToPercentInput(data.provision_rate ?? data.suggested_provision_rate))
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const coefficientOptions = COEFFICIENTS.some((c) => c.value === coefficient)
    ? COEFFICIENTS
    : [...COEFFICIENTS, { value: coefficient, label: `${rateToPercentInput(coefficient)}%` }]
  const automaticLabel =
    data.startup_last_year === null
      ? 'Automatica · 15% finché non indichi l’inizio attività'
      : `Automatica · ${data.year <= data.startup_last_year && data.year > data.startup_last_year - 5 ? '5%' : '15%'} (5% fino al ${data.startup_last_year})`
  const fixedOptions = TAX_RATES.some((t) => t.value === taxRate) || taxRate === AUTO ? TAX_RATES : [...TAX_RATES, { value: taxRate, label: `${rateToPercentInput(taxRate)}%` }]
  const taxOptions = [{ value: AUTO, label: automaticLabel }, ...fixedOptions]

  async function save() {
    if (!isPercentInput(inps)) return setError("L'aliquota INPS va da 0 a 100")
    if (custom && !isPercentInput(provision)) return setError("L'accantonamento va da 0 a 100")
    setError(null)
    try {
      await update.mutateAsync({
        year: data.year,
        payload: {
          profitability_coefficient: coefficient,
          substitute_tax_rate: taxRate === AUTO ? null : taxRate,
          inps_rate: percentInputToRate(inps),
          rivalsa_rate: rivalsa ? '0.0400' : '0.0000',
          provision_rate: custom ? percentInputToRate(provision) : null,
        },
      })
      setSaved(true)
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare i parametri.'))
    }
  }

  const pct = (rate: string, digits = 1) => formatPercent(toNumber(rate) * 100, { digits })
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-2.5 sm:grid-cols-2">
        <Field label="Coefficiente di redditività" htmlFor="fr-coefficient" hint="Dipende dal codice ATECO.">
          <select id="fr-coefficient" className="field" value={coefficient} onChange={(e) => setCoefficient(e.target.value)}>
            {coefficientOptions.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Imposta sostitutiva"
          htmlFor="fr-tax"
          hint="5% per l’anno di inizio e i quattro successivi, se ne hai i requisiti; poi 15%."
        >
          <select id="fr-tax" className="field" value={taxRate} onChange={(e) => setTaxRate(e.target.value)}>
            {taxOptions.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="INPS gestione separata" htmlFor="fr-inps" hint="L'aliquota cambia ogni anno: controlla la circolare INPS.">
          <PercentInput id="fr-inps" value={inps} onChange={setInps} />
        </Field>
        <div className="flex items-end">
          <label className="flex min-h-11 cursor-pointer items-center gap-2 text-[14px] font-semibold">
            <input type="checkbox" className="h-4 w-4" checked={rivalsa} onChange={(e) => setRivalsa(e.target.checked)} />
            Rivalsa INPS 4% in fattura
          </label>
        </div>
      </div>

      <fieldset className="flex flex-col gap-2 rounded-[12px] bg-card-2 px-3 py-3">
        <legend className="sr-only">Accantonamento {data.year}</legend>
        <p className="text-[13px] text-ink-2">
          Su ogni euro incassato: tasse e contributi dell'anno {pct(data.load_rate)}, acconti dell'anno dopo {pct(data.advance_rate)}. Al netto
          degli acconti già versati per il {data.year}, il fabbisogno è il <b className="text-ink">{pct(data.needed_rate)}</b>.
        </p>
        <label className="flex min-h-11 cursor-pointer items-center gap-2 text-[14px] font-semibold">
          <input type="radio" name="fr-provision" className="h-4 w-4" checked={!custom} onChange={() => setCustom(false)} />
          Consigliato: {pct(data.suggested_provision_rate, 0)}
          <span className="font-normal text-ink-3">(fabbisogno + margine, arrotondato al 5%)</span>
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex min-h-11 cursor-pointer items-center gap-2 text-[14px] font-semibold">
            <input type="radio" name="fr-provision" className="h-4 w-4" checked={custom} onChange={() => setCustom(true)} />
            Personalizzato
          </label>
          {custom && (
            <div className="w-28">
              <PercentInput id="fr-provision" value={provision} onChange={setProvision} />
            </div>
          )}
        </div>
      </fieldset>

      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={save} disabled={update.isPending}>
          {update.isPending ? 'Salvataggio…' : `Salva parametri ${data.year}`}
        </Button>
        {saved && <Saved>Parametri {data.year} salvati</Saved>}
      </div>
    </div>
  )
}

function ProvisionSources() {
  const { user } = useAuth()
  const base = user?.base_currency ?? ''
  const { data: provision, isLoading } = useProvision()
  const { data: accounts } = useAccounts()
  const { data: holdings } = useHoldings()
  const add = useAddProvisionSource()
  const remove = useRemoveProvisionSource()
  const [accountId, setAccountId] = useState('')
  const [assetId, setAssetId] = useState('')
  const [error, setError] = useState<string | null>(null)

  const products = (holdings ?? []).filter((h) => h.account_id === accountId)

  async function submit() {
    if (!accountId) return setError('Scegli un conto')
    setError(null)
    try {
      await add.mutateAsync({ account_id: accountId, asset_id: assetId || null })
      setAssetId('')
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile aggiungere.'))
    }
  }

  async function del(id: string) {
    setError(null)
    try {
      await remove.mutateAsync(id)
    } catch (e) {
      setError(apiErrorMessage(e))
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <SubHeading>Dove accantoni</SubHeading>
      <p className="text-[13px] text-ink-2">
        Conti e prodotti con i soldi messi da parte per tasse e contributi. Sono vincolati: non finanziano obiettivi di risparmio e non contano nei
        mesi di autonomia. Per un prodotto in un conto (es. un ETF monetario sul broker) aggiungi sia il conto, per la liquidità residua, sia il
        prodotto.
      </p>
      {isLoading ? (
        <LoadingBlock className="h-16" />
      ) : (
        <ul className="tabular-nums">
          {(provision?.sources ?? []).map((s) => (
            <li key={s.id} className="flex items-center gap-3 border-b border-line py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate font-bold">{s.asset ? `${s.asset.symbol} · ${s.asset.name}` : s.account_name}</div>
                <div className="text-[12px] text-ink-3">{s.asset ? `in ${s.account_name}` : 'liquidità del conto'}</div>
              </div>
              <span className="font-bold whitespace-nowrap">
                {s.value_base_currency === null ? 'n.d.' : formatAmount(s.value_base_currency, base)} <span className="ccy">{base}</span>
              </span>
              <Button size="sm" onClick={() => del(s.id)} disabled={remove.isPending}>
                Rimuovi
              </Button>
            </li>
          ))}
          {(provision?.sources ?? []).length === 0 && <li className="py-2 text-[13px] text-ink-3">Nessun conto o prodotto scelto.</li>}
        </ul>
      )}
      <div className="grid gap-2.5 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Field label="Conto" htmlFor="fr-source-account">
          <select
            id="fr-source-account"
            className="field"
            value={accountId}
            onChange={(e) => {
              setAccountId(e.target.value)
              setAssetId('')
            }}
          >
            <option value="">Scegli un conto</option>
            {(accounts ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Prodotto" htmlFor="fr-source-asset">
          <select id="fr-source-asset" className="field" value={assetId} onChange={(e) => setAssetId(e.target.value)} disabled={products.length === 0}>
            <option value="">Liquidità del conto</option>
            {products.map((h) => (
              <option key={h.id} value={h.asset.id}>
                {h.asset.symbol} · {h.asset.name}
              </option>
            ))}
          </select>
        </Field>
        <Button variant="primary" onClick={submit} disabled={add.isPending}>
          Aggiungi
        </Button>
      </div>
      {error && <ErrorBlock>{error}</ErrorBlock>}
    </div>
  )
}
