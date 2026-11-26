import type { Account, WaterfallAction } from '@/types'

// A goal's id (or the purpose, for the tax provision) plus the suggested
// source: one goal can be fed from several accounts — the spending account and a
// goal account's excess — and each is its own giroconto.
export function actionKey(a: WaterfallAction): string {
  return `${a.goal_id ?? a.purpose}:${a.from_account_id ?? ''}`
}

export interface Resolved {
  from: string | null
  to: string | null
  // The destination is picked here and will be linked to the goal.
  linking: boolean
  executable: boolean
  problem: string | null
}

// What the row will do once the user's picks are applied on top of the
// suggestion: the source can always be changed; a destination only when the
// goal has none (it then becomes the goal's account).
export function resolve(action: WaterfallAction, choice: Choice | undefined, accounts: Account[]): Resolved {
  const from = choice?.from ?? action.from_account_id
  const linking = action.to_account_id === null && action.purpose === 'goal'
  const to = action.to_account_id ?? choice?.to ?? null
  const fromAccount = accounts.find((a) => a.id === from)
  const toAccount = accounts.find((a) => a.id === to)
  let problem: string | null = null
  if (!from) problem = 'Scegli il conto da cui partire'
  else if (!to) problem = 'Scegli il conto in cui mettere questi soldi: verrà collegato all’obiettivo'
  else if (from === to) problem = 'Partenza e destinazione sono lo stesso conto'
  else if (fromAccount && toAccount && fromAccount.currency !== toAccount.currency)
    problem = `Valute diverse (${fromAccount.currency} → ${toAccount.currency}): fallo a mano con un cambio`
  return { from, to, linking, executable: problem === null, problem }
}

export type Choice = { from?: string; to?: string }
