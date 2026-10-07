import { useId, type ReactNode } from 'react'

interface CardProps {
  title?: ReactNode
  // Right side of the header: a link ("Gestisci"), a segmented control…
  action?: ReactNode
  // Inline next to the title: a total, a chip.
  meta?: ReactNode
  children: ReactNode
  className?: string
  padded?: boolean
  id?: string
}

/** The white panel every section sits on. Titled cards are a labelled <section>. */
export function Card({ title, action, meta, children, className = '', padded = true, id }: CardProps) {
  const headingId = useId()
  return (
    <section
      id={id}
      aria-labelledby={title ? headingId : undefined}
      className={`min-w-0 rounded-[14px] border border-line bg-card ${padded ? 'px-4 py-4 sm:px-5' : ''} ${className}`}
    >
      {(title || action) && (
        <div className={`flex flex-wrap items-center justify-between gap-x-3 gap-y-2 ${padded ? '' : 'px-4 pt-4 sm:px-5'}`}>
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
            {title && (
              <h2 id={headingId} className="text-[15px] font-extrabold">
                {title}
              </h2>
            )}
            {meta}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}
