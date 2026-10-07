export interface SegmentOption<T extends string> {
  value: T
  label: string
}

interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  label: string
  size?: 'sm' | 'md'
  className?: string
}

/** Mutually exclusive toggle buttons (aria-pressed), e.g. 1M/3M/1A or Tutti/Uscite. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  size = 'md',
  className = '',
}: SegmentedControlProps<T>) {
  return (
    <div role="group" aria-label={label} className={`inline-flex max-w-full gap-0.5 overflow-x-auto rounded-[10px] bg-card-2 p-[3px] ${className}`}>
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={`flex-none cursor-pointer rounded-lg px-3 whitespace-nowrap ${size === 'sm' ? 'min-h-8 text-[13px]' : 'min-h-[38px] text-[14px]'} ${
              active ? 'bg-card font-extrabold text-ink shadow-[0_1px_2px_rgba(0,0,0,0.14)]' : 'font-semibold text-ink-2 hover:text-ink'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
