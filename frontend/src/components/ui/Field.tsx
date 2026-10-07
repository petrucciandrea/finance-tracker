import type { LabelHTMLAttributes, ReactNode } from 'react'

export function Label({ className = '', ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={`mb-1.5 block text-[14px] font-bold text-ink ${className}`} {...props} />
}

interface FieldProps {
  label: ReactNode
  htmlFor: string
  error?: string
  hint?: ReactNode
  children: ReactNode
  className?: string
}

/**
 * Label + control + message. Wire the control with
 * aria-invalid={!!error} and aria-describedby={`${htmlFor}-msg`}.
 */
export function Field({ label, htmlFor, error, hint, children, className = '' }: FieldProps) {
  return (
    <div className={className}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? (
        <p id={`${htmlFor}-msg`} role="alert" className="mt-1.5 text-[13px] font-bold text-neg">
          ✕ {error}
        </p>
      ) : hint ? (
        <p id={`${htmlFor}-msg`} className="mt-1.5 text-[13px] text-ink-3">
          {hint}
        </p>
      ) : null}
    </div>
  )
}
