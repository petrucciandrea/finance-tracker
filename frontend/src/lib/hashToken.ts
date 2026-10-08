/**
 * Links in emails carry their signed token in the URL fragment (`#token=…`),
 * which browsers never send to a server, so it stays out of access logs and
 * Referer headers.
 */
export function readHashToken(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get('token')
}
