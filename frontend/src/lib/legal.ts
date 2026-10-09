/**
 * Who the privacy policy and terms name as data controller. Set at build time
 * (Render env vars) so the real identity never lives in the repo:
 *   VITE_LEGAL_CONTROLLER  name of the person/entity running the service
 *   VITE_LEGAL_EMAIL       public contact for privacy requests (not the admin mailbox)
 *   VITE_LEGAL_ADDRESS     optional postal address / seat
 *   VITE_LEGAL_HOSTING     optional: where the data is hosted, e.g. "Hetzner (Germania)"
 */
const env = import.meta.env

export const LEGAL = {
  controller: (env.VITE_LEGAL_CONTROLLER as string | undefined) ?? '',
  email: (env.VITE_LEGAL_EMAIL as string | undefined) ?? '',
  address: (env.VITE_LEGAL_ADDRESS as string | undefined) ?? '',
  hosting: (env.VITE_LEGAL_HOSTING as string | undefined) ?? '',
  // Mirror of the backend's TERMS_VERSION: bump both when the texts change.
  version: '2026-10',
  updatedOn: '8 ottobre 2026',
}

/** True while the controller identity is still missing: the pages say so loudly. */
export const LEGAL_INCOMPLETE = !LEGAL.controller || !LEGAL.email
