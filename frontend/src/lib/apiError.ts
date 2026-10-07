import { isAxiosError } from 'axios'
import type { ApiErrorResponse } from '@/types'

/**
 * The message from main.py's error envelope, else `fallback`. Backend
 * messages are in English, so `byStatus` lets a caller give its own
 * Italian text for the statuses it expects.
 */
export function apiErrorMessage(
  error: unknown,
  fallback = 'Si è verificato un errore. Riprova.',
  byStatus: Partial<Record<number, string>> = {},
): string {
  if (isAxiosError<ApiErrorResponse>(error)) {
    const status = error.response?.status
    if (status !== undefined && byStatus[status]) return byStatus[status]
    const message = error.response?.data?.error?.message
    if (message) return message
  }
  return fallback
}
