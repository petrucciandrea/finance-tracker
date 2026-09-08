/**
 * Auth state shared across the app: current user, login/register/logout,
 * and the "silent re-login" bootstrap on page load (access token lives only
 * in memory, so a refresh wipes it — we use the stored refresh token to get
 * a new one before rendering protected routes).
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import * as authApi from '@/api/auth'
import { getStoredRefreshToken, setAccessToken, setStoredRefreshToken } from '@/api/client'
import type { LoginPayload, RegisterPayload, User } from '@/types'

interface AuthContextValue {
  user: User | null
  isLoading: boolean // true only during the initial bootstrap, not during login/register calls
  login: (payload: LoginPayload) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
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
    await authApi.register(payload)
    // Registration doesn't log the user in on the backend — chain a login
    // so the UX is "register" -> immediately in the app, one less step.
    await login({ email: payload.email, password: payload.password })
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

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
