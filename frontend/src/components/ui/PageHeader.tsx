import type { ReactNode } from 'react'

/**
 * Page title row. Below lg the top bar already shows the page name, so the
 * <h1> stays for screen readers but is visually hidden there.
 */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
      <div className="min-w-0 flex-[1_1_260px]">
        <h1 className="text-[24px] font-extrabold tracking-[-0.02em] max-lg:sr-only">{title}</h1>
        {subtitle && <p className="text-[13px] font-semibold text-ink-3 tabular-nums">{subtitle}</p>}
      </div>
      {actions && <div className="flex max-w-full min-w-0 flex-[0_1_auto] flex-wrap gap-2 max-sm:flex-auto">{actions}</div>}
    </div>
  )
}
