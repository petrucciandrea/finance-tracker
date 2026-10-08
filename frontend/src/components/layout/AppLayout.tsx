import { useCallback, useEffect, useId, useMemo, useRef, useState, type ComponentType, type SVGProps } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ThemeChooser } from '@/components/layout/ThemeChooser'
import {
  ChevronDownIcon,
  CloseIcon,
  EyeIcon,
  EyeOffIcon,
  GemIcon,
  GridIcon,
  HomeIcon,
  ListIcon,
  LogOutIcon,
  MenuIcon,
  MoonIcon,
  PlanIcon,
  SunIcon,
  TrendIcon,
  UserIcon,
  WalletIcon,
} from '@/components/ui/Icon'
import { useAttentionCounts } from '@/hooks/useAttention'
import { useAuth } from '@/hooks/useAuth'
import { useDismiss } from '@/hooks/useDismiss'
import { useTheme } from '@/hooks/useTheme'
import { displayName, initials } from '@/lib/format'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<SVGProps<SVGSVGElement>>
  badge?: number
  badgeLabel?: string
}

// Budgets stay archived: no nav entry and no route (see App.tsx).
function useNavItems(): NavItem[] {
  const { toAssign, toClassify } = useAttentionCounts()
  return [
    { to: '/', label: 'Panoramica', icon: HomeIcon },
    {
      to: '/transactions',
      label: 'Transazioni',
      icon: ListIcon,
      badge: toAssign,
      badgeLabel: `${toAssign} movimenti in Varie da assegnare`,
    },
    { to: '/planning', label: 'Piano', icon: PlanIcon },
    { to: '/portfolio', label: 'Portafoglio', icon: TrendIcon },
    { to: '/assets', label: 'Beni', icon: GemIcon },
    { to: '/accounts', label: 'Conti', icon: WalletIcon },
    {
      to: '/categories',
      label: 'Categorie',
      icon: GridIcon,
      badge: toClassify,
      badgeLabel: `${toClassify} categorie senza livello di necessità`,
    },
  ]
}

const PAGE_TITLES: Record<string, string> = {
  '/profile': 'Profilo',
}

function Badge({ count, label }: { count?: number; label?: string }) {
  if (!count) return null
  return (
    <>
      <span
        aria-hidden="true"
        className="grid h-5 min-w-5 place-items-center rounded-full bg-warn-soft px-1.5 text-[11px] font-extrabold text-warn tabular-nums"
      >
        {count > 99 ? '99+' : count}
      </span>
      <span className="sr-only">, {label}</span>
    </>
  )
}

function Avatar({ text, strong = false, size = 34 }: { text: string; strong?: boolean; size?: number }) {
  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size }}
      className={`grid flex-none place-items-center rounded-full text-[12px] font-extrabold ${
        strong ? 'bg-accent text-on-accent' : 'bg-accent-soft text-accent'
      }`}
    >
      {text}
    </span>
  )
}

const menuItemClass =
  'flex min-h-11 w-full cursor-pointer items-center gap-2.5 rounded-[10px] px-3 text-left text-[14px] font-semibold text-ink hover:bg-card-2'

/**
 * Shell for every protected page: a sticky top bar (no side menu, no bottom
 * tab bar). From lg up the sections sit inline; below it a hamburger opens
 * a panel under the bar, and the bar shows the current page's name.
 */
export function AppLayout() {
  const { user, logout, setHideAmounts } = useAuth()
  const { resolved, setPreference } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const items = useNavItems()

  // Both popups remember the path they were opened on: navigating closes
  // them without an effect, because the stored path no longer matches.
  const [menuOpenAt, setMenuOpenAt] = useState<string | null>(null)
  const [accountOpenAt, setAccountOpenAt] = useState<string | null>(null)
  const menuOpen = menuOpenAt === location.pathname
  const accountOpen = accountOpenAt === location.pathname

  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const menuPanelRef = useRef<HTMLDivElement>(null)
  const accountButtonRef = useRef<HTMLButtonElement>(null)
  const accountPanelRef = useRef<HTMLDivElement>(null)
  const menuRefs = useMemo(() => [menuButtonRef, menuPanelRef], [])
  const accountRefs = useMemo(() => [accountButtonRef, accountPanelRef], [])
  const closeMenu = useCallback(() => setMenuOpenAt(null), [])
  const closeAccount = useCallback(() => setAccountOpenAt(null), [])
  useDismiss(menuOpen, menuRefs, closeMenu)
  useDismiss(accountOpen, accountRefs, closeAccount)

  const menuId = useId()
  const accountId = useId()

  // BrowserRouter keeps the window's scroll across navigations, so a new
  // page would open wherever the previous one was left (e.g. mid-dashboard
  // after logging in from the scrolled-down mobile form). Query-string
  // changes (filters, pagination) deliberately keep the position.
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [location.pathname])

  if (!user) return null // ProtectedRoute guarantees a user; this narrows the type.

  const name = displayName(user.first_name, user.last_name, user.email)
  const avatar = initials(user.first_name, user.last_name, user.email)
  const current =
    items.find((item) => (item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)))?.label ??
    PAGE_TITLES[location.pathname] ??
    ''

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  const nextTheme = resolved === 'dark' ? 'light' : 'dark'
  const themeToggleLabel = nextTheme === 'dark' ? 'Passa al tema scuro' : 'Passa al tema chiaro'
  const hidden = user.hide_amounts
  const amountsToggleLabel = hidden ? 'Mostra importi' : 'Nascondi importi'

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-line bg-card">
        <div className="mx-auto flex min-h-16 max-w-[1240px] items-center gap-3 px-3 sm:px-5">
          <button
            ref={menuButtonRef}
            type="button"
            onClick={() => {
              setAccountOpenAt(null)
              setMenuOpenAt(menuOpen ? null : location.pathname)
            }}
            aria-expanded={menuOpen}
            aria-controls={menuId}
            aria-label={menuOpen ? 'Chiudi menu' : 'Apri menu'}
            className="grid h-11 w-11 flex-none cursor-pointer place-items-center rounded-[10px] text-ink hover:bg-card-2 lg:hidden"
          >
            {menuOpen ? <CloseIcon className="h-[22px] w-[22px]" /> : <MenuIcon className="h-[22px] w-[22px]" />}
          </button>

          <Link to="/" className="mr-3 hidden items-center gap-2.5 text-[17px] font-extrabold text-ink lg:flex">
            <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-[14px] text-on-accent">
              F
            </span>
            Finanze
          </Link>

          {/* The page's own <h1> is visually hidden below lg; this is its visual stand-in. */}
          <p aria-hidden="true" className="min-w-0 flex-1 truncate text-[17px] font-extrabold lg:hidden">
            {current}
          </p>

          <nav aria-label="Principale" className="hidden min-w-0 flex-1 gap-0.5 lg:flex">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `flex min-h-10 items-center gap-1.5 rounded-[10px] px-3 text-[14px] whitespace-nowrap ${
                    isActive ? 'bg-accent-soft font-extrabold text-accent' : 'font-semibold text-ink-2 hover:bg-card-2'
                  }`
                }
              >
                {item.label}
                <Badge count={item.badge} label={item.badgeLabel} />
              </NavLink>
            ))}
          </nav>

          {/* Unlike the theme toggle, visible at every width: hiding the
              numbers is most useful on a phone, in public. */}
          <button
            type="button"
            onClick={() => setHideAmounts(!hidden)}
            aria-label={amountsToggleLabel}
            title={amountsToggleLabel}
            className="grid h-10 w-10 flex-none cursor-pointer place-items-center rounded-[10px] border border-line text-ink hover:bg-card-2"
          >
            {hidden ? <EyeOffIcon className="h-[18px] w-[18px]" /> : <EyeIcon className="h-[18px] w-[18px]" />}
          </button>

          <button
            type="button"
            onClick={() => setPreference(nextTheme)}
            aria-label={themeToggleLabel}
            title={themeToggleLabel}
            className="hidden h-10 w-10 flex-none cursor-pointer place-items-center rounded-[10px] border border-line text-ink hover:bg-card-2 lg:grid"
          >
            {resolved === 'dark' ? <SunIcon className="h-[18px] w-[18px]" /> : <MoonIcon className="h-[18px] w-[18px]" />}
          </button>

          <div className="relative">
            <button
              ref={accountButtonRef}
              type="button"
              onClick={() => {
                setMenuOpenAt(null)
                setAccountOpenAt(accountOpen ? null : location.pathname)
              }}
              aria-expanded={accountOpen}
              aria-controls={accountId}
              aria-label={`Account di ${name}, ${user.email}`}
              className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-full border-line p-1 lg:border lg:bg-card lg:pr-2.5"
            >
              <Avatar text={avatar} size={36} />
              <span className="hidden flex-col items-start leading-[1.2] lg:flex">
                <span className="text-[13px] font-extrabold">{name}</span>
                <span className="text-[12px] text-ink-3">
                  {user.email} · {user.base_currency}
                </span>
              </span>
              <ChevronDownIcon className="hidden h-3.5 w-3.5 lg:block" />
            </button>

            {accountOpen && (
              <div
                ref={accountPanelRef}
                id={accountId}
                className="absolute top-[calc(100%+8px)] right-0 z-30 w-[290px] rounded-[14px] border border-line bg-card p-1.5 shadow-[0_12px_32px_rgba(0,0,0,0.18)]"
              >
                <div className="mb-1.5 border-b border-line px-3 pt-2.5 pb-3">
                  <div className="font-extrabold">{name}</div>
                  <div className="truncate text-[13px] text-ink-3">{user.email}</div>
                  <div className="mt-1.5 text-[12px] font-bold text-ink-2">Valuta base {user.base_currency}</div>
                </div>
                <Link to="/profile" className={menuItemClass}>
                  <UserIcon className="h-[18px] w-[18px]" />
                  Profilo e impostazioni
                </Link>
                <div className="px-3 py-2">
                  <div className="mb-1.5 text-[12px] font-bold text-ink-3">Tema</div>
                  <ThemeChooser className="w-full [&>button]:flex-1" />
                </div>
                <button type="button" onClick={handleLogout} className={menuItemClass}>
                  <LogOutIcon className="h-[18px] w-[18px]" />
                  Esci
                </button>
              </div>
            )}
          </div>
        </div>

        {menuOpen && (
          <>
            {/* Scrim under the panel; clicks on it are caught by useDismiss. */}
            <div aria-hidden="true" className="fixed inset-x-0 top-16 bottom-0 z-10 bg-[rgba(16,24,40,0.45)] lg:hidden dark:bg-black/60" />
            <div
              ref={menuPanelRef}
              id={menuId}
              className="absolute inset-x-0 top-full z-20 max-h-[calc(100dvh-64px)] overflow-y-auto rounded-b-[20px] border-b border-line bg-card px-3 pt-2.5 pb-3.5 shadow-[0_16px_40px_rgba(0,0,0,0.25)] lg:hidden"
            >
              <Link to="/profile" className="mb-1.5 flex items-center gap-3 border-b border-line px-3 pt-2.5 pb-3.5 text-ink">
                <Avatar text={avatar} strong size={44} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-extrabold">{name}</span>
                  <span className="block truncate text-[13px] text-ink-3">
                    {user.email} · valuta {user.base_currency}
                  </span>
                </span>
                <span className="text-[13px] font-bold text-accent">Profilo ›</span>
              </Link>
              <nav aria-label="Principale">
                <ul className="flex flex-col gap-0.5">
                  {items.map((item) => (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        end={item.to === '/'}
                        className={({ isActive }) =>
                          `flex min-h-12 items-center gap-3 rounded-xl px-3 text-[15px] ${
                            isActive ? 'bg-accent-soft font-extrabold text-accent' : 'font-semibold text-ink hover:bg-card-2'
                          }`
                        }
                      >
                        <item.icon className="h-5 w-5" />
                        <span className="flex-1">{item.label}</span>
                        <Badge count={item.badge} label={item.badgeLabel} />
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </nav>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-line px-1 pt-3">
                <ThemeChooser size="md" />
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex min-h-11 cursor-pointer items-center gap-2 rounded-xl bg-card-2 px-4 font-semibold"
                >
                  <LogOutIcon className="h-[18px] w-[18px]" />
                  Esci
                </button>
              </div>
            </div>
          </>
        )}
      </header>

      <main className="w-full flex-1 px-4 pt-[22px] pb-12 sm:px-5">
        <div className="mx-auto flex max-w-[1200px] flex-col gap-4">
          {/* Remount on toggle: the formatters read the flag at render time,
              and memoised rows or chart tooltips wouldn't re-render on their
              own. Query data is cached and filters live in the URL, so
              only transient UI state (an open row, a draft) is lost. */}
          <Outlet key={hidden ? 'amounts-hidden' : 'amounts-shown'} />
        </div>
      </main>
    </div>
  )
}
