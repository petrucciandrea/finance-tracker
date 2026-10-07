import { ChevronLeftIcon, ChevronRightIcon } from '@/components/ui/Icon'

interface PaginationProps {
  page: number
  totalPages: number
  totalItems: number
  pageSize: number
  pageSizes: readonly number[]
  onPage: (page: number) => void
  onPageSize: (size: number) => void
}

/** 1 … 4 5 6 … 12 — first, last and the current page's neighbours. */
function pageWindow(page: number, total: number): (number | 'gap')[] {
  const pages = new Set([1, total, page - 1, page, page + 1].filter((p) => p >= 1 && p <= total))
  const sorted = [...pages].sort((a, b) => a - b)
  const out: (number | 'gap')[] = []
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push('gap')
    out.push(p)
  })
  return out
}

const pageButton =
  'grid min-h-11 min-w-11 cursor-pointer place-items-center rounded-[10px] px-2 text-[14px] font-bold disabled:cursor-not-allowed disabled:opacity-40'

export function Pagination({ page, totalPages, totalItems, pageSize, pageSizes, onPage, onPageSize }: PaginationProps) {
  const first = totalItems === 0 ? 0 : (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, totalItems)
  return (
    <nav
      aria-label="Paginazione"
      className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 tabular-nums"
    >
      <label className="flex items-center gap-2 text-[13px] text-ink-2">
        Righe per pagina
        <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))} className="field min-h-10 w-auto pr-8 text-[14px]">
          {pageSizes.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
      <span className="text-[13px] text-ink-2">
        <b className="text-ink">
          {first}–{last}
        </b>{' '}
        di {totalItems}
      </span>
      <div className="flex flex-wrap items-center gap-1">
        <button type="button" className={`${pageButton} gap-1`} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <span className="flex items-center gap-1">
            <ChevronLeftIcon />
            <span className="max-sm:sr-only">Precedente</span>
          </span>
        </button>
        {pageWindow(page, totalPages).map((p, i) =>
          p === 'gap' ? (
            <span key={`gap-${i}`} aria-hidden="true" className="px-1 text-ink-3">
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              aria-current={p === page ? 'page' : undefined}
              aria-label={`Pagina ${p}`}
              onClick={() => onPage(p)}
              className={`${pageButton} ${p === page ? 'bg-accent-soft text-accent' : 'text-ink-2 hover:bg-card-2'}`}
            >
              {p}
            </button>
          ),
        )}
        <button type="button" className={pageButton} disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
          <span className="flex items-center gap-1">
            <span className="max-sm:sr-only">Successiva</span>
            <ChevronRightIcon />
          </span>
        </button>
      </div>
    </nav>
  )
}
