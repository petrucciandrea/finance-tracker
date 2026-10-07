import { isAxiosError } from 'axios'
import type { ApiErrorResponse } from '@/types'

/** The message from main.py's error envelope, else `fallback`. */
export function apiErrorMessage(error: unknown, fallback = 'Si è verificato un errore. Riprova.'): string {
  if (isAxiosError<ApiErrorResponse>(error)) {
    const message = error.response?.data?.error?.message
    if (message) return message
  }
  return fallback
}
