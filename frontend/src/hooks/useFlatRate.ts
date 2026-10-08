import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as flatRateApi from '@/api/flatRate'
import { PLANNING_KEY } from '@/hooks/usePlanning'
import { invalidatePortfolio } from '@/hooks/usePortfolio'
import { TRANSACTIONS_KEY } from '@/hooks/useTransactions'
import type {
  FlatRateSettingsUpdatePayload,
  FlatRateYearUpdatePayload,
  InvoiceCollectPayload,
  InvoiceCreatePayload,
  InvoiceUpdatePayload,
  ProvisionSourceCreatePayload,
  TaxPaymentCreatePayload,
  TaxPaymentUpdatePayload,
} from '@/types'

const FLAT_RATE_KEY = ['flat-rate'] as const

export function useFlatRateSettings() {
  return useQuery({ queryKey: [...FLAT_RATE_KEY, 'settings'], queryFn: flatRateApi.getSettings })
}

export function useFlatRateYear(year: number) {
  return useQuery({ queryKey: [...FLAT_RATE_KEY, 'year', year], queryFn: () => flatRateApi.getYear(year) })
}

export function useFlatRateSummary(year: number) {
  return useQuery({ queryKey: [...FLAT_RATE_KEY, 'summary', year], queryFn: () => flatRateApi.getSummary(year) })
}

export function useInvoices(year: number) {
  return useQuery({ queryKey: [...FLAT_RATE_KEY, 'invoices', year], queryFn: () => flatRateApi.listInvoices(year) })
}

/** Clients already invoiced, most recent first — the invoice form's suggestions. */
export function useInvoiceClients() {
  return useQuery({ queryKey: [...FLAT_RATE_KEY, 'clients'], queryFn: flatRateApi.listClients })
}

export function useTaxPayments(year: number) {
  return useQuery({ queryKey: [...FLAT_RATE_KEY, 'payments', year], queryFn: () => flatRateApi.listPayments(year) })
}

export function useProvision() {
  return useQuery({ queryKey: [...FLAT_RATE_KEY, 'provision'], queryFn: flatRateApi.getProvision })
}

export function useCollectionCandidates(invoiceId: string | null) {
  return useQuery({
    queryKey: [...FLAT_RATE_KEY, 'candidates', invoiceId],
    queryFn: () => flatRateApi.collectionCandidates(invoiceId!),
    enabled: invoiceId !== null,
  })
}

/**
 * Every write here can move the year's figures, the suggested rate (it
 * depends on what's collected), the liability in net worth and its history;
 * collecting onto an account or paying an F24 also moves cash, the
 * transactions list and the runway. Invalidate all of it, as Beni does.
 */
function useInvalidate() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: FLAT_RATE_KEY })
    invalidatePortfolio(queryClient)
    queryClient.invalidateQueries({ queryKey: TRANSACTIONS_KEY })
    queryClient.invalidateQueries({ queryKey: PLANNING_KEY })
  }
}

export function useUpdateFlatRateSettings() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (payload: FlatRateSettingsUpdatePayload) => flatRateApi.updateSettings(payload), onSuccess })
}

export function useUpdateFlatRateYear() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ year, payload }: { year: number; payload: FlatRateYearUpdatePayload }) => flatRateApi.updateYear(year, payload),
    onSuccess,
  })
}

export function useCreateInvoice() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (payload: InvoiceCreatePayload) => flatRateApi.createInvoice(payload), onSuccess })
}

export function useUpdateInvoice() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: InvoiceUpdatePayload }) => flatRateApi.updateInvoice(id, payload),
    onSuccess,
  })
}

export function useDeleteInvoice() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (id: string) => flatRateApi.deleteInvoice(id), onSuccess })
}

export function useCollectInvoice() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: InvoiceCollectPayload }) => flatRateApi.collectInvoice(id, payload),
    onSuccess,
  })
}

export function useUncollectInvoice() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (id: string) => flatRateApi.uncollectInvoice(id), onSuccess })
}

export function useCreateTaxPayment() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (payload: TaxPaymentCreatePayload) => flatRateApi.createPayment(payload), onSuccess })
}

export function useUpdateTaxPayment() {
  const onSuccess = useInvalidate()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: TaxPaymentUpdatePayload }) => flatRateApi.updatePayment(id, payload),
    onSuccess,
  })
}

export function useDeleteTaxPayment() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (id: string) => flatRateApi.deletePayment(id), onSuccess })
}

export function useAddProvisionSource() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (payload: ProvisionSourceCreatePayload) => flatRateApi.addProvisionSource(payload), onSuccess })
}

export function useRemoveProvisionSource() {
  const onSuccess = useInvalidate()
  return useMutation({ mutationFn: (id: string) => flatRateApi.removeProvisionSource(id), onSuccess })
}
