import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { CheckIcon, MoonIcon, SunIcon } from '@/components/ui/Icon'
import { useTheme } from '@/hooks/useTheme'

const POINTS = [
  'Più valute, ogni importo convertito nella tua valuta base',
  'Import dei movimenti da CSV, con controllo dei duplicati',
  'Piano di ripartizione delle entrate e portafoglio titoli',
]

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `grid min-h-11 place-items-center rounded-[9px] text-[14px] ${
    isActive ? 'bg-card font-extrabold text-ink shadow-[0_1px_2px_rgba(0,0,0,0.14)]' : 'font-semibold text-ink-2 hover:text-ink'
  }`

/**
 * Split screen for /login and /register: a dark brand panel with the three
 * selling points, the form on the right. The two "tabs" are links between
 * the routes, so each form keeps its own URL.
 */
export function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  const { resolved, setPreference } = useTheme()
  const next = resolved === 'dark' ? 'light' : 'dark'

  return (
    <div className="flex min-h-screen flex-wrap">
      <aside className="flex min-h-[280px] flex-[1_1_420px] flex-col gap-10 bg-brand-bg px-6 py-10 text-brand-ink sm:px-14 sm:py-12">
        <div className="flex items-center gap-2.5 text-[18px] font-extrabold">
          <span aria-hidden="true" className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-brand-ink text-[15px] text-brand-bg">
            F
          </span>
          Finanze
        </div>
        <div className="mt-auto max-w-[460px]">
          <p className="text-[28px] leading-[1.15] font-extrabold tracking-[-0.02em] sm:text-[34px]">
            Conti, piano e investimenti in un unico posto.
          </p>
          <ul className="mt-7 flex flex-col gap-3.5 text-[15px] text-brand-ink-2">
            {POINTS.map((point) => (
              <li key={point} className="flex gap-3">
                <CheckIcon className="mt-0.5 h-5 w-5 flex-none" />
                {point}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-[13px] text-brand-ink-2">Strumento personale · i tuoi dati restano sul tuo server</p>
      </aside>

      <main className="grid flex-[1_1_520px] place-items-center px-4 py-12 sm:px-6">
        <div className="w-full max-w-[420px]">
          <nav aria-label="Accesso" className="grid grid-cols-2 gap-0.5 rounded-xl border border-line bg-card-2 p-1">
            <NavLink to="/login" className={tabClass}>
              Accedi
            </NavLink>
            <NavLink to="/register" className={tabClass}>
              Crea account
            </NavLink>
          </nav>

          <h1 className="mt-7 mb-1 text-[26px] font-extrabold tracking-[-0.02em]">{title}</h1>
          <p className="text-[15px] text-ink-2">{subtitle}</p>

          {children}

          <div className="mt-7 flex justify-center">
            <button
              type="button"
              onClick={() => setPreference(next)}
              className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-[10px] border border-line px-3 text-[13px] font-bold"
            >
              {next === 'dark' ? <MoonIcon /> : <SunIcon />}
              {next === 'dark' ? 'Tema scuro' : 'Tema chiaro'}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
