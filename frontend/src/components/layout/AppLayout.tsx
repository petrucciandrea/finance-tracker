import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium ${
    isActive ? 'bg-slate-800 text-white' : 'text-slate-600 hover:bg-slate-100'
  }`

/**
 * Shell for every protected page: top nav + logout, with the actual page
 * rendered via <Outlet />. Nested under <ProtectedRoute> in App.tsx, so by
 * the time this renders we already know `user` is not null.
 */
export function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={navLinkClass}>
              Dashboard
            </NavLink>
            <NavLink to="/transactions" className={navLinkClass}>
              Transazioni
            </NavLink>
            <NavLink to="/accounts" className={navLinkClass}>
              Conti
            </NavLink>
            <NavLink to="/categories" className={navLinkClass}>
              Categorie
            </NavLink>
            <NavLink to="/import" className={navLinkClass}>
              Importa CSV
            </NavLink>
          </nav>

          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-500">{user?.email}</span>
            <button
              onClick={handleLogout}
              className="rounded-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
            >
              Esci
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
