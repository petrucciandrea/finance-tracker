import { useState, type ReactNode } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { WorkSettings } from '@/components/flat-rate/WorkSettings'
import { ThemeChooser } from '@/components/layout/ThemeChooser'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/Dialog'
import { ErrorBlock } from '@/components/ui/EmptyState'
import { Field } from '@/components/ui/Field'
import { CheckIcon, LogOutIcon } from '@/components/ui/Icon'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { downloadMyData } from '@/api/auth'
import { useAuth } from '@/hooks/useAuth'
import { apiErrorMessage } from '@/lib/apiError'
import { CURRENCIES, CURRENCY_NAMES, type CurrencyCode } from '@/lib/currencies'
import { displayName, formatFullDate, initials } from '@/lib/format'

const SECTIONS = [
  { id: 'dati', label: 'Dati personali' },
  { id: 'valuta', label: 'Valuta base' },
  { id: 'lavoro', label: 'Lavoro' },
  { id: 'aspetto', label: 'Aspetto' },
  { id: 'password', label: 'Password' },
  { id: 'privacy', label: 'Dati e privacy' },
]

const MIN_PASSWORD = 8

function Section({ id, title, description, children }: { id: string; title: string; description?: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-24 rounded-[14px] border border-line bg-card px-4 py-5 sm:px-6">
      <h2 id={`${id}-title`} className="text-[16px] font-extrabold">
        {title}
      </h2>
      {description && <p className="mt-1 text-[14px] text-ink-2">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Saved({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="inline-flex items-center gap-1.5 text-[13px] font-bold text-pos">
      <CheckIcon /> {children}
    </p>
  )
}

const profileSchema = z.object({
  first_name: z.string().max(100, 'Massimo 100 caratteri').optional(),
  last_name: z.string().max(100, 'Massimo 100 caratteri').optional(),
  email: z.string().email('Inserisci un indirizzo email valido'),
  date_of_birth: z.string().optional(),
})
type ProfileValues = z.infer<typeof profileSchema>

function PersonalData() {
  const { user, updateProfile } = useAuth()
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      first_name: user?.first_name ?? '',
      last_name: user?.last_name ?? '',
      email: user?.email ?? '',
      date_of_birth: user?.date_of_birth ?? '',
    },
  })

  async function onSubmit(values: ProfileValues) {
    setSaved(false)
    setError(null)
    try {
      await updateProfile({
        email: values.email,
        // An empty field means "clear it" — null, not "", so it round-trips
        // as an actual absence of data.
        first_name: values.first_name || null,
        last_name: values.last_name || null,
        date_of_birth: values.date_of_birth || null,
      })
      reset(values)
      setSaved(true)
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile salvare il profilo. Riprova.', { 409: 'Esiste già un account con questa email.' }))
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-4 sm:grid-cols-2">
      <Field label="Nome" htmlFor="first_name" error={errors.first_name?.message}>
        <input id="first_name" autoComplete="given-name" className="field" {...register('first_name')} />
      </Field>
      <Field label="Cognome" htmlFor="last_name" error={errors.last_name?.message}>
        <input id="last_name" autoComplete="family-name" className="field" {...register('last_name')} />
      </Field>
      <Field label="Email" htmlFor="email" error={errors.email?.message}>
        <input
          id="email"
          type="email"
          autoComplete="email"
          className="field"
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? 'email-msg' : undefined}
          {...register('email')}
        />
      </Field>
      <Field label="Data di nascita" htmlFor="date_of_birth" hint="Facoltativa.">
        <input id="date_of_birth" type="date" className="field" aria-describedby="date_of_birth-msg" {...register('date_of_birth')} />
      </Field>
      <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
        <Button type="submit" variant="primary" disabled={isSubmitting || !isDirty}>
          {isSubmitting ? 'Salvataggio…' : 'Salva dati'}
        </Button>
        {saved && !isDirty && <Saved>Dati salvati</Saved>}
      </div>
      {error && (
        <div className="sm:col-span-2">
          <ErrorBlock>{error}</ErrorBlock>
        </div>
      )}
    </form>
  )
}

function BaseCurrency() {
  const { user, updateProfile } = useAuth()
  const queryClient = useQueryClient()
  const [pending, setPending] = useState<CurrencyCode | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const current = user?.base_currency

  async function confirm() {
    if (!pending) return
    setSaving(true)
    setError(null)
    try {
      await updateProfile({ base_currency: pending })
      // No query key carries the currency, so every cached figure is now
      // in the wrong unit: refetch everything.
      await queryClient.invalidateQueries()
      setPending(null)
      setSaved(true)
    } catch (e) {
      setError(apiErrorMessage(e, 'Impossibile cambiare la valuta.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div role="radiogroup" aria-label="Valuta base" className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2">
        {CURRENCIES.map((code) => {
          const on = code === current
          return (
            <button
              key={code}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => {
                setSaved(false)
                if (!on) setPending(code)
              }}
              className={`flex min-h-14 cursor-pointer flex-col items-start justify-center rounded-[12px] border px-3 py-2 text-left ${
                on ? 'border-accent bg-accent-soft text-accent' : 'border-field bg-card hover:bg-card-2'
              }`}
            >
              <span className="text-[15px] font-extrabold">{code}</span>
              <span className={`text-[12px] ${on ? 'text-accent' : 'text-ink-3'}`}>{CURRENCY_NAMES[code]}</span>
            </button>
          )
        })}
      </div>
      {saved && (
        <div className="mt-3">
          <Saved>Valuta base aggiornata a {current}</Saved>
        </div>
      )}
      <ConfirmDialog
        open={!!pending}
        tone="primary"
        title={`Passare da ${current} a ${pending}?`}
        confirmLabel={`Usa ${pending}`}
        pending={saving}
        error={error}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      >
        <p className="rounded-[10px] bg-warn-soft px-3 py-2 font-bold text-warn">
          I movimenti già registrati restano convertiti in {current} al cambio del loro giorno: non vengono ricalcolati.
        </p>
        <p className="mt-2">
          Da qui in poi i nuovi movimenti saranno convertiti in {pending}. Totali, grafici e piano dei periodi passati sommerebbero quindi importi
          in due valute diverse. Conviene cambiarla solo se hai appena iniziato.
        </p>
      </ConfirmDialog>
    </>
  )
}

const passwordSchema = z
  .object({
    current_password: z.string().min(1, 'Inserisci la password attuale'),
    new_password: z.string().min(MIN_PASSWORD, `Almeno ${MIN_PASSWORD} caratteri`),
    confirm_password: z.string().min(1, 'Conferma la nuova password'),
  })
  .refine((v) => v.new_password !== v.current_password, { message: 'Deve essere diversa da quella attuale', path: ['new_password'] })
  .refine((v) => v.new_password === v.confirm_password, { message: 'Le due password non coincidono', path: ['confirm_password'] })
type PasswordValues = z.infer<typeof passwordSchema>

function ChangePassword() {
  const { changePassword } = useAuth()
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isSubmitting },
  } = useForm<PasswordValues>({
    resolver: zodResolver(passwordSchema),
    mode: 'onChange',
    defaultValues: { current_password: '', new_password: '', confirm_password: '' },
  })
  const [currentPw, newPw, confirmPw] = useWatch({ control, name: ['current_password', 'new_password', 'confirm_password'] })

  const rules = [
    { ok: newPw.length >= MIN_PASSWORD, label: `Almeno ${MIN_PASSWORD} caratteri` },
    { ok: newPw.length > 0 && newPw !== currentPw, label: 'Diversa da quella attuale' },
    { ok: confirmPw.length > 0 && confirmPw === newPw, label: 'Le due password coincidono' },
  ]
  const valid = currentPw.length > 0 && rules.every((r) => r.ok)
  const mismatch = confirmPw.length > 0 && confirmPw !== newPw

  async function onSubmit(values: PasswordValues) {
    setSaved(false)
    setError(null)
    try {
      await changePassword({ current_password: values.current_password, new_password: values.new_password })
      reset()
      setSaved(true)
    } catch (e) {
      // 401 here means the current password is wrong (the client doesn't
      // retry this endpoint after a refresh — see api/client.ts).
      setError(apiErrorMessage(e, 'Si è verificato un errore. Riprova.', { 401: 'La password attuale non è corretta.' }))
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex max-w-[560px] flex-col gap-4">
      <Field label="Password attuale" htmlFor="current_password">
        <PasswordInput id="current_password" autoComplete="current-password" {...register('current_password')} />
      </Field>
      <Field label="Nuova password" htmlFor="new_password">
        <PasswordInput id="new_password" autoComplete="new-password" aria-describedby="pw-rules" {...register('new_password')} />
      </Field>
      <ul id="pw-rules" className="-mt-2 flex flex-col gap-1 text-[13px]">
        {rules.map((rule) => (
          <li key={rule.label} className={`flex items-center gap-1.5 font-semibold ${rule.ok ? 'text-pos' : 'text-ink-3'}`}>
            <span aria-hidden="true">{rule.ok ? '✓' : '○'}</span>
            {rule.label}
            <span className="sr-only">{rule.ok ? ' (soddisfatto)' : ' (non ancora)'}</span>
          </li>
        ))}
      </ul>
      <Field label="Conferma nuova password" htmlFor="confirm_password" error={mismatch ? errors.confirm_password?.message ?? 'Le due password non coincidono' : undefined}>
        <PasswordInput
          id="confirm_password"
          autoComplete="new-password"
          aria-invalid={mismatch}
          aria-describedby={mismatch ? 'confirm_password-msg' : undefined}
          {...register('confirm_password')}
        />
      </Field>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={!valid || isSubmitting}>
          {isSubmitting ? 'Aggiornamento…' : 'Cambia password'}
        </Button>
        {saved && <Saved>Password aggiornata</Saved>}
      </div>
    </form>
  )
}

function DataAndPrivacy() {
  const { deleteAccount } = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [password, setPassword] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function handleDownload() {
    setDownloading(true)
    setDownloadError(null)
    try {
      await downloadMyData()
    } catch (e) {
      setDownloadError(apiErrorMessage(e, 'Non sono riuscito a scaricare i dati. Riprova.'))
    } finally {
      setDownloading(false)
    }
  }

  function closeDialog() {
    setConfirming(false)
    setPassword('')
    setDeleteError(null)
  }

  async function handleDelete() {
    if (password.length === 0) {
      setDeleteError('Inserisci la password per confermare.')
      return
    }
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteAccount(password)
      // Cached data belongs to the account that no longer exists.
      queryClient.clear()
      navigate('/login', { replace: true })
    } catch (e) {
      setDeleteError(apiErrorMessage(e, 'Non sono riuscito a eliminare l’account. Riprova.', { 403: 'La password non è corretta.' }))
      setDeleting(false)
    }
  }

  return (
    <div className="flex max-w-[560px] flex-col gap-5">
      <div className="flex flex-col items-start gap-2">
        <p className="text-[14px] text-ink-2">
          Scarica una copia di tutti i tuoi dati (conti, movimenti, investimenti, beni, fatture…) in un file JSON.
        </p>
        <Button onClick={handleDownload} disabled={downloading}>
          {downloading ? 'Preparazione…' : 'Scarica i miei dati'}
        </Button>
        {downloadError && <ErrorBlock>{downloadError}</ErrorBlock>}
      </div>

      <div className="flex flex-col items-start gap-2 border-t border-line pt-5">
        <p className="text-[14px] text-ink-2">
          Elimina il tuo account e tutti i dati collegati. L’operazione è definitiva e non si può annullare: scarica
          prima una copia, se ti serve.
        </p>
        <Button variant="danger" onClick={() => setConfirming(true)}>
          Elimina account…
        </Button>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Eliminare l’account?"
        confirmLabel="Elimina definitivamente"
        onConfirm={handleDelete}
        onCancel={closeDialog}
        pending={deleting}
        error={deleteError}
      >
        <p className="mb-3 text-[14px] text-ink-2">
          Verranno cancellati subito e per sempre conti, movimenti, investimenti, beni, fatture e ogni altro dato. Per
          confermare inserisci la tua password.
        </p>
        <Field label="Password" htmlFor="delete_password">
          <PasswordInput
            id="delete_password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
      </ConfirmDialog>
    </div>
  )
}

export function ProfilePage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  if (!user) return null
  const name = displayName(user.first_name, user.last_name, user.email)
  const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ') || name

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <>
      <section aria-label="Account" className="flex flex-wrap items-center gap-4 rounded-[14px] border border-line bg-card px-4 py-5 sm:px-6">
        <span aria-hidden="true" className="grid h-12 w-12 flex-none place-items-center rounded-full bg-accent text-[18px] font-extrabold text-on-accent sm:h-16 sm:w-16 sm:text-[22px]">
          {initials(user.first_name, user.last_name, user.email)}
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="text-[22px] font-extrabold tracking-[-0.02em]">{fullName}</h1>
          <p className="truncate text-[14px] text-ink-2">{user.email}</p>
          <p className="mt-0.5 text-[13px] text-ink-3">
            Valuta base <b className="text-ink-2">{user.base_currency}</b> · account creato il {formatFullDate(user.created_at.slice(0, 10))}
          </p>
        </div>
        <Button onClick={handleLogout} className="max-sm:w-full">
          <LogOutIcon />
          Esci
        </Button>
      </section>

      <div className="flex flex-wrap items-start gap-4">
        <nav aria-label="Sezioni del profilo" className="sticky top-20 hidden w-[200px] flex-none rounded-[14px] border border-line bg-card p-1.5 lg:block">
          <ul>
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a href={`#${section.id}`} className="flex min-h-11 items-center rounded-[10px] px-3 text-[14px] font-semibold text-ink-2 hover:bg-card-2 hover:text-ink">
                  {section.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex min-w-0 flex-[1_1_560px] flex-col gap-4">
          <Section id="dati" title="Dati personali">
            <PersonalData />
          </Section>
          <Section id="valuta" title="Valuta base" description="La valuta in cui vedi totali, grafici e piano. Ogni movimento resta nella sua valuta originale.">
            <BaseCurrency />
          </Section>
          <Section
            id="lavoro"
            title="Lavoro"
            description="Il tipo di lavoro sblocca le sezioni dedicate. Con la P.IVA forfettaria: fatture, tasse e quanto accantonare."
          >
            <WorkSettings />
          </Section>
          <Section id="aspetto" title="Aspetto" description="“Sistema” segue l'impostazione chiaro/scuro del dispositivo.">
            <ThemeChooser size="md" />
          </Section>
          <Section id="password" title="Cambia password">
            <ChangePassword />
          </Section>
          <Section id="privacy" title="Dati e privacy" description="Una copia dei tuoi dati, o la cancellazione definitiva dell’account.">
            <DataAndPrivacy />
          </Section>
        </div>
      </div>
    </>
  )
}
