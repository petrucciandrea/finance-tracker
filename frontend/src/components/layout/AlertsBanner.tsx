import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertIcon, CloseIcon } from '@/components/ui/Icon'
import { useAlerts } from '@/hooks/useAlerts'
import { alertText } from '@/lib/alerts'
import type { Alert } from '@/types'

const STORAGE_KEY = 'dismissed-alerts'
const VISIBLE = 3

// `every_visit` alerts hidden in this visit. Module state, not component
// state: it must survive the banner remounting (the amounts toggle re-keys
// it) and end with the page — a reload is opening the app again.
const hiddenThisVisit = new Set<string>()

// Per-viewer convenience only: storage may be missing (private window,
// blocked site data), in which case a "once" alert just comes back.
function readDismissed(): Set<string> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

function writeDismissed(ids: Set<string>): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]))
  } catch {
    // Nothing to do: see readDismissed.
  }
}

/**
 * The things that need attention, at the top of every page. Two kinds of
 * dismissal: an `every_visit` alert (an account that can't cover a
 * scheduled debit, a deadline within two weeks) only hides until the app is
 * opened again — a reload brings it back (see `hiddenThisVisit`); a `once`
 * alert (an account getting close to its debits) is dismissed for good,
 * until its id changes because the commitment did.
 */
export function AlertsBanner() {
  const { data } = useAlerts()
  const [, rerender] = useState(0)
  const [dismissed, setDismissed] = useState<Set<string>>(readDismissed)
  const [expanded, setExpanded] = useState(false)

  const alerts = (data?.alerts ?? []).filter((a) => !hiddenThisVisit.has(a.id) && !(a.repeat === 'once' && dismissed.has(a.id)))
  if (alerts.length === 0) return null

  function dismiss(alert: Alert) {
    if (alert.repeat === 'once') {
      // Only ids still current are worth keeping: the list can't grow forever.
      const live = new Set((data?.alerts ?? []).map((a) => a.id))
      const next = new Set([...dismissed].filter((id) => live.has(id)))
      next.add(alert.id)
      writeDismissed(next)
      setDismissed(next)
    } else {
      hiddenThisVisit.add(alert.id)
      rerender((n) => n + 1)
    }
  }

  const shown = expanded ? alerts : alerts.slice(0, VISIBLE)
  return (
    <section aria-label="Avvisi" className="flex flex-col gap-2">
      {shown.map((alert) => {
        const { title, body } = alertText(alert)
        const danger = alert.tone === 'danger'
        return (
          <div
            key={alert.id}
            role={danger ? 'alert' : 'status'}
            className={`flex items-start gap-2.5 rounded-[12px] px-3 py-2.5 text-[13px] ${danger ? 'bg-neg-soft text-neg' : 'bg-warn-soft text-warn'}`}
          >
            <AlertIcon className="mt-0.5 h-[18px] w-[18px] flex-none" />
            <div className="min-w-0 flex-1">
              <p className="font-extrabold">{title}</p>
              <p className="mt-0.5 font-semibold tabular-nums">
                {body}
                {alert.link && (
                  <>
                    {' '}
                    <Link to={alert.link} className="font-extrabold underline underline-offset-2">
                      Vai
                    </Link>
                  </>
                )}
              </p>
            </div>
            <button
              type="button"
              onClick={() => dismiss(alert)}
              aria-label={alert.repeat === 'once' ? 'Ignora questo avviso' : 'Nascondi fino al prossimo accesso'}
              title={alert.repeat === 'once' ? 'Ignora' : 'Nascondi fino al prossimo accesso'}
              className="-mt-1 -mr-1 grid h-9 w-9 flex-none cursor-pointer place-items-center rounded-[8px] hover:bg-black/5 dark:hover:bg-white/10"
            >
              <CloseIcon className="h-4 w-4" />
            </button>
          </div>
        )
      })}
      {alerts.length > VISIBLE && (
        <button type="button" onClick={() => setExpanded(!expanded)} className="self-start text-[13px] font-bold text-accent underline-offset-2 hover:underline">
          {expanded ? 'Mostra meno' : `Mostra altri ${alerts.length - VISIBLE} avvisi`}
        </button>
      )}
    </section>
  )
}
