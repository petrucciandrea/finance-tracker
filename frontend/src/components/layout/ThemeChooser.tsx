import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useTheme } from '@/hooks/useTheme'
import type { ThemePreference } from '@/context/theme'

const OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: 'system', label: 'Sistema' },
  { value: 'light', label: 'Chiaro' },
  { value: 'dark', label: 'Scuro' },
]

export function ThemeChooser({ size = 'sm', className = '' }: { size?: 'sm' | 'md'; className?: string }) {
  const { preference, setPreference } = useTheme()
  return (
    <SegmentedControl
      label="Tema"
      options={OPTIONS}
      value={preference}
      onChange={setPreference}
      size={size}
      className={className}
    />
  )
}
