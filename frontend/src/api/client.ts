/**
 * Axios instance shared by every api/*.ts module.
 *
 * Handles:
 * - Attaching the access token to every request.
 * - Transparently refreshing an expired access token on a 401 and retrying
 *   the original request once — callers never see the 401 or know a
 *   refresh happened.
 * - Queueing requests that arrive while a refresh is already in flight, so
 *   concurrent 401s don't trigger multiple simultaneous refresh calls
 *   (which would race on the backend's refresh-token rotation and cause
 *   one of them to fail).
 */

import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { TokenPair } from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

// In-memory only — never localStorage. Lost on page refresh by design; the
// refresh token (in localStorage) is what lets us silently re-authenticate
// on load. See AuthContext for that bootstrap logic.
let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

const REFRESH_TOKEN_STORAGE_KEY = 'finance_tracker_refresh_token'

export function getStoredRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)
}

export function setStoredRefreshToken(token: string | null) {
  if (token) {
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token)
  } else {
    localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY)
  }
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
})

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

// --- 401 handling: refresh once, retry, queue concurrent requests ---

let isRefreshing = false
let pendingRequests: Array<(token: string | null) => void> = []

function subscribeToRefresh(callback: (token: string | null) => void) {
  pendingRequests.push(callback)
}

function notifyRefreshSubscribers(token: string | null) {
  pendingRequests.forEach((callback) => callback(token))
  pendingRequests = []
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetriableConfig | undefined

    // Also excludes /auth/me/password: a 401 there means "wrong current
    // password", a business error the caller must show as-is — retrying
    // it after a token refresh would just re-send the same wrong password
    // and burn a refresh-token rotation for nothing.
    const isAuthEndpoint = originalRequest?.url?.includes('/auth/login') ||
      originalRequest?.url?.includes('/auth/register') ||
      originalRequest?.url?.includes('/auth/refresh') ||
      originalRequest?.url?.includes('/auth/me/password')

    if (error.response?.status !== 401 || !originalRequest || originalRequest._retry || isAuthEndpoint) {
      return Promise.reject(error)
    }

    originalRequest._retry = true

    if (isRefreshing) {
      // A refresh is already in flight — wait for it instead of firing a
      // second one, then retry this request with whatever token comes out.
      return new Promise((resolve, reject) => {
        subscribeToRefresh((newToken) => {
          if (!newToken) {
            reject(error)
            return
          }
          originalRequest.headers.Authorization = `Bearer ${newToken}`
          resolve(apiClient(originalRequest))
        })
      })
    }

    isRefreshing = true
    const refreshToken = getStoredRefreshToken()

    if (!refreshToken) {
      isRefreshing = false
      notifyRefreshSubscribers(null)
      return Promise.reject(error)
    }

    try {
      const { data } = await axios.post<TokenPair>(`${API_BASE_URL}/auth/refresh`, {
        refresh_token: refreshToken,
      })

      setAccessToken(data.access_token)
      setStoredRefreshToken(data.refresh_token) // rotation: backend issues a new one each time

      notifyRefreshSubscribers(data.access_token)
      originalRequest.headers.Authorization = `Bearer ${data.access_token}`
      return apiClient(originalRequest)
    } catch (refreshError) {
      // Refresh token itself is invalid/expired/revoked — full logout.
      setAccessToken(null)
      setStoredRefreshToken(null)
      notifyRefreshSubscribers(null)
      return Promise.reject(refreshError)
    } finally {
      isRefreshing = false
    }
  },
)
