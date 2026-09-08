import { apiClient } from './client'
import type {
  Transaction,
  TransactionCreatePayload,
  TransactionImportPreview,
  TransactionListParams,
  TransactionListResponse,
  TransactionSummaryParams,
  TransactionSummaryResponse,
} from '@/types'

export async function listTransactions(params: TransactionListParams = {}): Promise<TransactionListResponse> {
  const { data } = await apiClient.get<TransactionListResponse>('/transactions', { params })
  return data
}

export async function createTransaction(payload: TransactionCreatePayload): Promise<Transaction> {
  const { data } = await apiClient.post<Transaction>('/transactions', payload)
  return data
}

export async function deleteTransaction(id: string): Promise<void> {
  await apiClient.delete(`/transactions/${id}`)
}

export async function getSummary(params: TransactionSummaryParams = {}): Promise<TransactionSummaryResponse> {
  const { data } = await apiClient.get<TransactionSummaryResponse>('/transactions/summary', { params })
  return data
}

// --- CSV import (two-step: preview, then confirm) ---

export async function importPreview(accountId: string, file: File): Promise<TransactionImportPreview> {
  const formData = new FormData()
  formData.append('file', file)

  // account_id is a query param on the backend (not a Form field) — the
  // endpoint mixes UploadFile with a plain UUID param, which FastAPI
  // resolves as a query parameter rather than multipart form data.
  const { data } = await apiClient.post<TransactionImportPreview>('/transactions/import', formData, {
    params: { account_id: accountId },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function confirmImport(importId: string, rowNumbers: number[]): Promise<Transaction[]> {
  const { data } = await apiClient.post<Transaction[]>('/transactions/import/confirm', {
    import_id: importId,
    row_numbers: rowNumbers,
  })
  return data
}
