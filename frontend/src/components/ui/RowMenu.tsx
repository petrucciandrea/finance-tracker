import { useEffect, useId, useRef, useState } from 'react'
import { MoreIcon } from '@/components/ui/Icon'

export interface RowMenuItem {
  label: string
  onSelect: () => void
  tone?: 'default' | 'danger'
  disabled?: boolean
}

/**
 * The "⋯" button holding a row's actions — keeps destructive actions out of
 * sight until asked for, instead of a red bin on every row.
 *
 * The list is position: fixed, computed from the button, because rows often
 * live inside `overflow-x-auto` tables that would clip an absolute popup.
 */
export function RowMenu({ label, items }: { label: string; items: RowMenuItem[] }) {
  const [position, setPosition] = useState<{ top: number; right: number } | null>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const menuId = useId()
  const open = position !== null

  function openMenu() {
    const rect = buttonRef.current?.getBoundingClientRect()
    if (!rect) return
    setPosition({ top: rect.bottom + 4, right: window.innerWidth - rect.right })
  }

  function close(returnFocus = true) {
    setPosition(null)
    if (returnFocus) buttonRef.current?.focus()
  }

  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (!listRef.current?.contains(target) && !buttonRef.current?.contains(target)) setPosition(null)
    }
    // The fixed popup would drift away from its row on scroll.
    const onScroll = () => setPosition(null)
    document.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [open])

  function onKeyDown(event: React.KeyboardEvent) {
    const buttons = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      buttons[(index + 1) % buttons.length]?.focus()
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      buttons[(index - 1 + buttons.length) % buttons.length]?.focus()
    } else if (event.key === 'Tab') {
      close(false)
    }
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => (open ? close() : openMenu())}
        className="grid h-11 w-11 cursor-pointer place-items-center rounded-[10px] text-ink-2 hover:bg-card-2 hover:text-ink"
      >
        <MoreIcon className="h-5 w-5" />
      </button>
      {open && (
        <ul
          ref={listRef}
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={onKeyDown}
          style={{ top: position.top, right: position.right }}
          className="fixed z-50 min-w-[200px] rounded-[14px] border border-line bg-card p-1.5 shadow-[0_12px_32px_rgba(0,0,0,0.18)]"
        >
          {items.map((item) => (
            <li key={item.label} role="none">
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  close()
                  item.onSelect()
                }}
                className={`flex min-h-11 w-full cursor-pointer items-center rounded-[10px] px-3 text-left text-[14px] font-semibold hover:bg-card-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                  item.tone === 'danger' ? 'text-neg' : 'text-ink'
                }`}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
