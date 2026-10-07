// Lives outside components/ui/Button.tsx so links (<Link className={buttonClass()}>)
// can look like buttons without that module exporting a non-component.

export type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const VARIANTS: Record<Variant, string> = {
  primary: 'border-transparent bg-accent text-on-accent hover:brightness-110',
  secondary: 'border-line bg-card text-ink hover:bg-card-2',
  ghost: 'border-transparent bg-transparent text-ink-2 hover:bg-card-2',
  danger: 'border-transparent bg-neg text-white dark:text-bg hover:brightness-110',
}

// min-h-11 = 44px, the touch-target floor; `size="sm"` is only for dense
// toolbars on desktop and still stays at 36px.
export type ButtonSize = 'md' | 'sm'

const SIZES: Record<ButtonSize, string> = {
  md: 'min-h-11 px-4 text-[14px]',
  sm: 'min-h-9 px-3 text-[13px]',
}

export function buttonClass(variant: Variant = 'secondary', size: ButtonSize = 'md') {
  return `inline-flex items-center justify-center gap-2 rounded-[10px] border font-bold whitespace-nowrap cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]}`
}
