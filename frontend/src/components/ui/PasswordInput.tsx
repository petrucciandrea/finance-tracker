import { useState, type InputHTMLAttributes, type Ref } from 'react'

interface PasswordInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  ref?: Ref<HTMLInputElement>
}

/** Password field with a Mostra/Nascondi toggle (aria-pressed). */
export function PasswordInput({ className = '', ref, ...props }: PasswordInputProps) {
  const [shown, setShown] = useState(false)
  return (
    <div className="relative">
      <input ref={ref} type={shown ? 'text' : 'password'} className={`field pr-24 ${className}`} {...props} />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-pressed={shown}
        aria-label={shown ? 'Nascondi password' : 'Mostra password'}
        className="absolute inset-y-1 right-1 cursor-pointer rounded-lg bg-card-2 px-3 text-[13px] font-bold text-ink"
      >
        {shown ? 'Nascondi' : 'Mostra'}
      </button>
    </div>
  )
}
