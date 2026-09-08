import { apiClient } from './client'
import type { Account, AccountCreatePayload, AccountUpdatePayload } from '@/types'

export async function listAccounts(): Promise<Account[]> {
  const { data } = await apiClient.get<Account[]>('/accounts')
  return data
}

export async function createAccount(payload: AccountCreatePayload): Promise<Account> {
  const { data } = await apiClient.post<Account>('/accounts', payload)
  return data
}

export async function getAccount(id: string): Promise<Account> {
  const { data } = await apiClient.get<Account>(`/accounts/${id}`)
  return data
}

export async function updateAccount(id: string, payload: AccountUpdatePayload): Promise<Account> {
  const { data } = await apiClient.patch<Account>(`/accounts/${id}`, payload)
  return data
}

export async function deleteAccount(id: string): Promise<void> {
  await apiClient.delete(`/accounts/${id}`)
}
