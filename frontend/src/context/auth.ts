// The context object lives apart from AuthProvider so that AuthContext.tsx
// exports only a component — mixing in non-component exports breaks Vite's
// fast refresh for that file (react-refresh/only-export-components).

import { createContext } from 'react'
import type { LoginPayload, PasswordChangePayload, RegisterPayload, User, UserUpdatePayload } from '@/types'

export interface AuthContextValue {
  user: User | null
  isLoading: boolean // true only during the initial bootstrap, not during login/register calls
  login: (payload: LoginPayload) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => Promise<void>
  updateProfile: (payload: UserUpdatePayload) => Promise<void>
  changePassword: (payload: PasswordChangePayload) => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
