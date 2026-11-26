import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { LightbulbIcon } from '@/components/ui/Icon'

const WIDTH = 320
const GUTTER = 16

/**
 * A lightbulb that opens an explanation as a bubble. For the "how this
 * works" sentences: they matter the first time and are noise afterwards, so
 * they stay one click away instead of lengthening every card. Warnings and
 * anything the user must act on stay in plain sight — never put those here.
 *
 * The bubble is position: fixed, computed from the button, like RowMenu: it
 * often sits inside `overflow-x-auto` blocks or a <dialog> that would clip an
 * absolute one. It opens below, or above when it wouldn't fit. Spans, not
 * divs, so it can sit inside a <p>; not a portal, because inside a modal
 * <dialog> anything outside it is inert.
 */
export function Tip({ children, label = 'Come funziona', className = '' }: { children: ReactNode; label?: string; className?: string }) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null)
  const [style, setStyle] = useState<React.CSSProperties>({ visibility: 'hidden' })
  const buttonRef = useRef<HTMLButtonElement>(null)
  const bubbleRef = useRef<HTMLSpanElement>(null)
  const bubbleId = useId()
  const open = anchor !== null

  function toggle() {
    if (open) setAnchor(null)
    else if (buttonRef.current) {
      // Measured at its final width, still invisible, before being placed.
      setStyle({ visibility: 'hidden', top: 0, left: 0, width: Math.min(WIDTH, window.innerWidth - 2 * GUTTER) })
      setAnchor(buttonRef.current.getBoundingClientRect())
    }
  }

  // Placed after render, once the bubble's height is known.
  useLayoutEffect(() => {
    if (!anchor || !bubbleRef.current) return
    const width = Math.min(WIDTH, window.innerWidth - 2 * GUTTER)
    const left = Math.min(Math.max(GUTTER, anchor.left), window.innerWidth - GUTTER - width)
    const height = bubbleRef.current.offsetHeight
    const below = anchor.bottom + 6
    const top = below + height > window.innerHeight - GUTTER && anchor.top - 6 - height > GUTTER ? anchor.top - 6 - height : below
    setStyle({ top, left, width })
  }, [anchor])

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (!bubbleRef.current?.contains(target) && !buttonRef.current?.contains(target)) setAnchor(null)
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      // Inside a <dialog>, Esc must close the bubble, not the dialog.
      event.preventDefault()
      event.stopPropagation()
      setAnchor(null)
      buttonRef.current?.focus()
    }
    // A fixed bubble would drift away from its button on scroll.
    const close = () => setAnchor(null)
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown, true)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown, true)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open])

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={open ? bubbleId : undefined}
        aria-label={label}
        title={label}
        onClick={toggle}
        className={`inline-grid h-8 w-8 flex-none cursor-pointer place-items-center rounded-[10px] align-middle ${
          open ? 'bg-accent-soft text-accent' : 'text-ink-3 hover:bg-card-2 hover:text-accent'
        } ${className}`}
      >
        <LightbulbIcon className="h-[18px] w-[18px]" />
      </button>
      {open && (
        <span
          ref={bubbleRef}
          id={bubbleId}
          role="note"
          style={style}
          className="fixed z-50 flex gap-2 rounded-[12px] border border-line bg-accent-soft px-3 py-2.5 text-left text-[13px] font-normal text-ink shadow-[0_12px_32px_rgba(0,0,0,0.18)]"
        >
          <LightbulbIcon className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <span className="flex min-w-0 flex-col gap-1">{children}</span>
        </span>
      )}
    </>
  )
}
