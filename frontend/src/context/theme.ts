// Kept apart from ThemeProvider for the same reason as context/auth.ts:
// a module exporting a component must export only components (fast refresh).

import { createContext } from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'

// Also read by the inline script in index.html, which applies the theme
// before React mounts — keep the two in sync.
export const THEME_STORAGE_KEY = 'finance_tracker_theme'

export interface ThemeContextValue {
  preference: ThemePreference
  // What is actually on screen once 'system' is resolved.
  resolved: 'light' | 'dark'
  setPreference: (preference: ThemePreference) => void
}

export const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)
