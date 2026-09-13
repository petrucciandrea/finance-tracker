import { apiClient } from './client'
import type {
  LoginPayload,
  PasswordChangePayload,
  RegisterPayload,
  TokenPair,
  User,
  UserUpdatePayload,
} from '@/types'

export async function register(payload: RegisterPayload): Promise<User> {
  const { data } = await apiClient.post<User>('/auth/register', payload)
  return data
}

export async function login(payload: LoginPayload): Promise<TokenPair> {
  const { data } = await apiClient.post<TokenPair>('/auth/login', payload)
  return data
}

export async function refresh(refreshToken: string): Promise<TokenPair> {
  const { data } = await apiClient.post<TokenPair>('/auth/refresh', { refresh_token: refreshToken })
  return data
}

export async function logout(refreshToken: string): Promise<void> {
  await apiClient.post('/auth/logout', { refresh_token: refreshToken })
}

export async function getCurrentUser(): Promise<User> {
  const { data } = await apiClient.get<User>('/auth/me')
  return data
}

export async function updateProfile(payload: UserUpdatePayload): Promise<User> {
  const { data } = await apiClient.patch<User>('/auth/me', payload)
  return data
}

export async function changePassword(payload: PasswordChangePayload): Promise<void> {
  await apiClient.post('/auth/me/password', payload)
}
