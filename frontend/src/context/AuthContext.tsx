/**
 * Auth state shared across the app: current user, login/register/logout,
 * and the "silent re-login" bootstrap on page load (access token lives only
 * in memory, so a refresh wipes it — we use the stored refresh token to get
 * a new one before rendering protected routes).
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'
import * as authApi from '@/api/auth'
import { getStoredRefreshToken, setAccessToken, setStoredRefreshToken } from '@/api/client'
import { AuthContext } from '@/context/auth'
import { setAmountsHidden } from '@/lib/format'
import type { LoginPayload, PasswordChangePayload, RegisterPayload, User, UserUpdatePayload } from '@/types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const didBootstrap = useRef(false)
  const hideAmountsRequest = useRef(0)

  // Every user change goes through here so the formatters' "hide amounts"
  // flag is already set when the next render runs (see lib/format.ts).
  // Logging out clears it: the login page has no amounts, and the next
  // account brings its own preference.
  function setUser(next: User | null) {
    setAmountsHidden(next?.hide_amounts ?? false)
    setUserState(next)
  }

  useEffect(() => {
    // StrictMode double-invokes effects in dev, which would otherwise fire
    // this twice with the same stored refresh token. Since refresh tokens
    // are single-use (revoked on rotation), the second call always 401s and
    // wipes a session that just successfully refreshed. A ref survives the
    // simulated remount (only effects re-run, not component state), so this
    // guard makes the bootstrap body run at most once per real mount.
    if (didBootstrap.current) return
    didBootstrap.current = true

    async function bootstrap() {
      const storedRefreshToken = getStoredRefreshToken()
      if (!storedRefreshToken) {
        setIsLoading(false)
        return
      }

      try {
        const tokens = await authApi.refresh(storedRefreshToken)
        setAccessToken(tokens.access_token)
        setStoredRefreshToken(tokens.refresh_token)
        const currentUser = await authApi.getCurrentUser()
        setUser(currentUser)
      } catch {
        // Stored refresh token is invalid/expired/revoked — treat as logged out.
        setAccessToken(null)
        setStoredRefreshToken(null)
      } finally {
        setIsLoading(false)
      }
    }

    bootstrap()
  }, [])

  async function login(payload: LoginPayload) {
    const tokens = await authApi.login(payload)
    setAccessToken(tokens.access_token)
    setStoredRefreshToken(tokens.refresh_token)
    const currentUser = await authApi.getCurrentUser()
    setUser(currentUser)
  }

  async function register(payload: RegisterPayload) {
    const created = await authApi.register(payload)
    // Registration doesn't log the user in on the backend — chain a login
    // so the UX is "register" -> immediately in the app, one less step.
    // A pending account can't log in yet (403), so skip it.
    if (created.approval_status === 'approved') {
      await login({ email: payload.email, password: payload.password })
    }
    return created
  }

  async function logout() {
    const storedRefreshToken = getStoredRefreshToken()
    if (storedRefreshToken) {
      try {
        await authApi.logout(storedRefreshToken)
      } catch {
        // Even if the server call fails (e.g. already expired), still clear
        // local state below — the user's intent to log out wins either way.
      }
    }
    setAccessToken(null)
    setStoredRefreshToken(null)
    setUser(null)
  }

  async function deleteAccount(password: string) {
    await authApi.deleteAccount(password)
    // The server already dropped every token with the account, so there is
    // nothing to revoke (unlike logout): just forget the session locally.
    setAccessToken(null)
    setStoredRefreshToken(null)
    setUser(null)
  }

  async function updateProfile(payload: UserUpdatePayload) {
    const updatedUser = await authApi.updateProfile(payload)
    setUser(updatedUser)
  }

  async function changePassword(payload: PasswordChangePayload) {
    // The server revokes every session on a password change and returns a
    // fresh pair for this one; without storing it we'd be logged out at the
    // next token refresh.
    const tokens = await authApi.changePassword(payload)
    setAccessToken(tokens.access_token)
    setStoredRefreshToken(tokens.refresh_token)
  }

  // Optimistic: the toggle must feel instant. Only a failure of the latest
  // request reverts — an older one failing after a newer click would
  // otherwise undo what the user just chose.
  function setHideAmounts(hidden: boolean) {
    if (!user) return
    const previous = user
    const request = ++hideAmountsRequest.current
    setUser({ ...user, hide_amounts: hidden })
    authApi.updateProfile({ hide_amounts: hidden }).catch(() => {
      if (request === hideAmountsRequest.current) setUser(previous)
    })
  }

  return (
    <AuthContext.Provider
      value={{ user, isLoading, login, register, logout, updateProfile, changePassword, deleteAccount, setHideAmounts }}
    >
      {children}
    </AuthContext.Provider>
  )
}

