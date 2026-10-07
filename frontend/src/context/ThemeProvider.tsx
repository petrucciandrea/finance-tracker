/**
 * Light/dark theme: the user's choice (Sistema/Chiaro/Scuro) persisted in
 * localStorage, applied as a `.dark` class on <html> — the Tailwind dark
 * variant keys off that class, not the media query, so the user can
 * override the OS. index.html applies the same rule before first paint.
 */

import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { THEME_STORAGE_KEY, ThemeContext, type ThemePreference } from '@/context/theme'

const DARK_QUERY = '(prefers-color-scheme: dark)'

function readStoredPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // Storage can throw in private windows; the default is fine there.
  }
  return 'system'
}

function subscribeToSystemTheme(onChange: () => void) {
  const media = window.matchMedia(DARK_QUERY)
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}

const systemPrefersDark = () => window.matchMedia(DARK_QUERY).matches

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference)
  const systemDark = useSyncExternalStore(subscribeToSystemTheme, systemPrefersDark)
  const resolved = preference === 'system' ? (systemDark ? 'dark' : 'light') : preference

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [resolved])

  function setPreference(next: ThemePreference) {
    setPreferenceState(next)
    try {
      if (next === 'system') localStorage.removeItem(THEME_STORAGE_KEY)
      else localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // Not persisted, but still applied for this session.
    }
  }

  return (
    <ThemeContext.Provider value={{ preference, resolved, setPreference }}>
      {children}
    </ThemeContext.Provider>
  )
}
