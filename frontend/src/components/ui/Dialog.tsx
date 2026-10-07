import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Button } from '@/components/ui/Button'
import { CloseIcon } from '@/components/ui/Icon'

interface DialogProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
}

const WIDTHS = { sm: 'max-w-[440px]', md: 'max-w-[560px]', lg: 'max-w-[880px]' }

/**
 * Modal on top of the native <dialog>: showModal() gives focus trapping,
 * Esc-to-close, inert background and a top layer for free — none of which
 * window.confirm or a hand-rolled overlay get right.
 */
export function Dialog({ open, onClose, title, description, children, footer, size = 'sm' }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    else if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      // Fires on Esc as well as on close(); the parent owns `open`.
      onClose={onClose}
      // A click on the backdrop lands on the <dialog> element itself.
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className={`m-auto w-[calc(100%-32px)] ${WIDTHS[size]} max-h-[calc(100dvh-32px)] rounded-2xl border border-line bg-card p-0 text-ink shadow-[0_24px_60px_rgba(0,0,0,0.3)] backdrop:bg-[rgba(16,24,40,0.5)]`}
    >
      {open && (
        <div className="flex flex-col gap-4 p-5 sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 id={titleId} className="text-[18px] font-extrabold tracking-[-0.01em]">
                {title}
              </h2>
              {description && (
                <p id={descriptionId} className="mt-1 text-[14px] text-ink-2">
                  {description}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Chiudi"
              className="-mt-2 -mr-2 grid h-11 w-11 flex-none cursor-pointer place-items-center rounded-[10px] text-ink-2 hover:bg-card-2"
            >
              <CloseIcon className="h-5 w-5" />
            </button>
          </div>
          {children}
          {footer && <div className="flex flex-wrap justify-end gap-2">{footer}</div>}
        </div>
      )}
    </dialog>
  )
}

interface ConfirmDialogProps {
  open: boolean
  title: ReactNode
  children?: ReactNode
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  pending?: boolean
  error?: string | null
  tone?: 'danger' | 'primary'
}

/** "Are you sure?" with the destructive action spelled out on the button. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  onConfirm,
  onCancel,
  pending = false,
  error,
  tone = 'danger',
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button onClick={onCancel}>Annulla</Button>
          <Button variant={tone} onClick={onConfirm} disabled={pending}>
            {pending ? 'Attendi…' : confirmLabel}
          </Button>
        </>
      }
    >
      {children && <div className="text-[14px] text-ink-2">{children}</div>}
      {error && (
        <p role="alert" className="rounded-[10px] bg-neg-soft px-3 py-2 text-[13px] font-bold text-neg">
          {error}
        </p>
      )}
    </Dialog>
  )
}
