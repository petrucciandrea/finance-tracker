import { apiClient } from './client'
import type {
  FlatRateSettings,
  FlatRateSettingsUpdatePayload,
  FlatRateSummary,
  FlatRateYear,
  FlatRateYearUpdatePayload,
  Invoice,
  InvoiceCollectPayload,
  InvoiceCreatePayload,
  InvoiceStatus,
  InvoiceUpdatePayload,
  ProvisionSourceCreatePayload,
  ProvisionStatus,
  TaxPayment,
  TaxPaymentCreatePayload,
  TaxPaymentUpdatePayload,
  Transaction,
} from '@/types'

const BASE = '/flat-rate'

export async function getSettings(): Promise<FlatRateSettings> {
  const { data } = await apiClient.get<FlatRateSettings>(`${BASE}/settings`)
  return data
}

export async function updateSettings(payload: FlatRateSettingsUpdatePayload): Promise<FlatRateSettings> {
  const { data } = await apiClient.patch<FlatRateSettings>(`${BASE}/settings`, payload)
  return data
}

export async function getYear(year: number): Promise<FlatRateYear> {
  const { data } = await apiClient.get<FlatRateYear>(`${BASE}/years/${year}`)
  return data
}

export async function updateYear(year: number, payload: FlatRateYearUpdatePayload): Promise<FlatRateYear> {
  const { data } = await apiClient.patch<FlatRateYear>(`${BASE}/years/${year}`, payload)
  return data
}

export async function getSummary(year: number): Promise<FlatRateSummary> {
  const { data } = await apiClient.get<FlatRateSummary>(`${BASE}/summary`, { params: { year } })
  return data
}

export async function listInvoices(year: number, status?: InvoiceStatus): Promise<Invoice[]> {
  const { data } = await apiClient.get<Invoice[]>(`${BASE}/invoices`, { params: { year, status } })
  return data
}

export async function listClients(): Promise<string[]> {
  const { data } = await apiClient.get<string[]>(`${BASE}/clients`)
  return data
}

export async function createInvoice(payload: InvoiceCreatePayload): Promise<Invoice> {
  const { data } = await apiClient.post<Invoice>(`${BASE}/invoices`, payload)
  return data
}

export async function updateInvoice(id: string, payload: InvoiceUpdatePayload): Promise<Invoice> {
  const { data } = await apiClient.patch<Invoice>(`${BASE}/invoices/${id}`, payload)
  return data
}

export async function deleteInvoice(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/invoices/${id}`)
}

export async function collectInvoice(id: string, payload: InvoiceCollectPayload): Promise<Invoice> {
  const { data } = await apiClient.post<Invoice>(`${BASE}/invoices/${id}/collect`, payload)
  return data
}

export async function uncollectInvoice(id: string): Promise<Invoice> {
  const { data } = await apiClient.post<Invoice>(`${BASE}/invoices/${id}/uncollect`)
  return data
}

export async function collectionCandidates(id: string): Promise<Transaction[]> {
  const { data } = await apiClient.get<Transaction[]>(`${BASE}/invoices/${id}/candidates`)
  return data
}

export async function listPayments(year: number): Promise<TaxPayment[]> {
  const { data } = await apiClient.get<TaxPayment[]>(`${BASE}/payments`, { params: { year } })
  return data
}

export async function createPayment(payload: TaxPaymentCreatePayload): Promise<TaxPayment> {
  const { data } = await apiClient.post<TaxPayment>(`${BASE}/payments`, payload)
  return data
}

export async function updatePayment(id: string, payload: TaxPaymentUpdatePayload): Promise<TaxPayment> {
  const { data } = await apiClient.patch<TaxPayment>(`${BASE}/payments/${id}`, payload)
  return data
}

export async function deletePayment(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/payments/${id}`)
}

export async function getProvision(): Promise<ProvisionStatus> {
  const { data } = await apiClient.get<ProvisionStatus>(`${BASE}/sources`)
  return data
}

export async function addProvisionSource(payload: ProvisionSourceCreatePayload): Promise<ProvisionStatus> {
  const { data } = await apiClient.post<ProvisionStatus>(`${BASE}/sources`, payload)
  return data
}

export async function removeProvisionSource(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/sources/${id}`)
}
