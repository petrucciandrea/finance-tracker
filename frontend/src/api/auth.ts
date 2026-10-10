import { apiClient } from './client'
import type {
  ApprovalRequestInfo,
  PublicConfig,
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

export async function changePassword(payload: PasswordChangePayload): Promise<TokenPair> {
  const { data } = await apiClient.post<TokenPair>('/auth/me/password', payload)
  return data
}

/** Downloads the full export as a file; the JSON is built server-side. */
export async function downloadMyData(): Promise<void> {
  const { data } = await apiClient.get<Blob>('/auth/me/export', { responseType: 'blob' })
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = 'finanze-export.json'
  link.click()
  URL.revokeObjectURL(url)
}

export async function deleteAccount(password: string): Promise<void> {
  await apiClient.delete('/auth/me', { data: { password } })
}

export async function previewApproval(token: string): Promise<ApprovalRequestInfo> {
  const { data } = await apiClient.post<ApprovalRequestInfo>('/auth/approvals/preview', { token })
  return data
}

export async function decideApproval(token: string, decision: 'approve' | 'reject'): Promise<ApprovalRequestInfo> {
  const { data } = await apiClient.post<ApprovalRequestInfo>('/auth/approvals/decision', { token, decision })
  return data
}

export async function verifyEmail(token: string): Promise<void> {
  await apiClient.post('/auth/email/verify', { token })
}

export async function resendVerification(email: string): Promise<void> {
  await apiClient.post('/auth/email/resend-verification', { email })
}

export async function requestPasswordReset(email: string): Promise<void> {
  await apiClient.post('/auth/password-reset/request', { email })
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<void> {
  await apiClient.post('/auth/password-reset/confirm', { token, new_password: newPassword })
}

export async function getPublicConfig(): Promise<PublicConfig> {
  const { data } = await apiClient.get<PublicConfig>('/auth/config')
  return data
}
