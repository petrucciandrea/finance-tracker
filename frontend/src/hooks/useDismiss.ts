import { useEffect, type RefObject } from 'react'

/**
 * Closes a popup on Esc or on a pointer-down outside every ref given (the
 * popup and the button that opened it — otherwise the opening click would
 * immediately count as "outside"). Pass the opening button first: Esc hands
 * focus back to it, so keyboard users aren't dropped at the top of the page.
 */
export function useDismiss(open: boolean, refs: RefObject<HTMLElement | null>[], onDismiss: () => void) {
  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (!refs.some((ref) => ref.current?.contains(target))) onDismiss()
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      onDismiss()
      refs[0]?.current?.focus()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, refs, onDismiss])
}
