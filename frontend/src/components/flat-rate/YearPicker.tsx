import { Button } from '@/components/ui/Button'
import { ChevronLeftIcon, ChevronRightIcon } from '@/components/ui/Icon'

export function YearPicker({ year, onChange }: { year: number; onChange: (year: number) => void }) {
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Anno">
      <Button variant="ghost" aria-label={`Anno ${year - 1}`} onClick={() => onChange(year - 1)}>
        <ChevronLeftIcon />
      </Button>
      <span className="min-w-12 text-center text-[15px] font-extrabold tabular-nums" aria-live="polite">
        {year}
      </span>
      <Button variant="ghost" aria-label={`Anno ${year + 1}`} onClick={() => onChange(year + 1)}>
        <ChevronRightIcon />
      </Button>
    </div>
  )
}
