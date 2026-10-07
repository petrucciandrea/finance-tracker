import type { ButtonHTMLAttributes } from 'react'
import { buttonClass, type ButtonSize, type Variant } from '@/lib/buttonClass'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: ButtonSize
}

export function Button({ variant = 'secondary', size = 'md', className = '', type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={`${buttonClass(variant, size)} ${className}`} {...props} />
}
