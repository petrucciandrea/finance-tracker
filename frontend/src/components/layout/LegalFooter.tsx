import { Link } from 'react-router-dom'

export function LegalFooter({ className = '' }: { className?: string }) {
  return (
    <footer className={`flex flex-wrap justify-center gap-x-5 gap-y-1 text-[13px] text-ink-3 ${className}`}>
      <Link to="/privacy" className="link">
        Privacy
      </Link>
      <Link to="/termini" className="link">
        Termini di servizio
      </Link>
    </footer>
  )
}
