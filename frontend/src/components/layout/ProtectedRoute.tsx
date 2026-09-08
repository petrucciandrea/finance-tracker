import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'

/**
 * Guards a route subtree: while the auth bootstrap is still resolving
 * (checking the stored refresh token), shows nothing rather than flashing
 * a login screen; once resolved, either renders the nested routes (Outlet)
 * or redirects to /login.
 */
export function ProtectedRoute() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <p className="text-slate-500">Caricamento...</p>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
