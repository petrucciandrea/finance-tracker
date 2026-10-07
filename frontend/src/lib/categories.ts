import type { Category, CategoryType, NecessityLevel, Transaction } from '@/types'

// The backend files every expense/income that arrives without a category
// under a top-level "Varie" of the matching type (routers/transactions.py,
// MISC_CATEGORY_NAME). It is the closest thing to "uncategorised" the data
// has, so the UI treats rows there as still to be assigned.
export const MISC_CATEGORY_NAME = 'Varie'

export function isMiscCategory(category: Category | undefined): boolean {
  return !!category && category.parent_id === null && category.name === MISC_CATEGORY_NAME
}

export const NECESSITY_LABELS: Record<NecessityLevel, string> = {
  primary: 'Primario',
  useful: 'Utile',
  discretionary: 'Accessorio',
}

export const CATEGORY_TYPE_LABELS: Record<CategoryType, string> = {
  expense: 'Spese',
  income: 'Entrate',
  transfer: 'Trasferimenti',
}

export function indexById<T extends { id: string }>(items: T[] | undefined): Map<string, T> {
  return new Map((items ?? []).map((item) => [item.id, item]))
}

/** Level a category resolves to: its own, else its parent's (one level deep, like the backend). */
export function categoryNecessity(
  category: Category | undefined,
  byId: Map<string, Category>,
): { level: NecessityLevel | null; inherited: boolean } {
  if (!category) return { level: null, inherited: false }
  if (category.necessity_level) return { level: category.necessity_level, inherited: false }
  const parent = category.parent_id ? byId.get(category.parent_id) : undefined
  return { level: parent?.necessity_level ?? null, inherited: !!parent?.necessity_level }
}

/**
 * Effective level of an expense, mirroring the backend's
 * COALESCE(override, category, parent). `source` tells the UI whether it
 * was set on the row ('override') or comes from the category tree.
 */
export function transactionNecessity(
  transaction: Transaction,
  byId: Map<string, Category>,
): { level: NecessityLevel | null; source: 'override' | 'category' | null } {
  if (transaction.type !== 'expense') return { level: null, source: null }
  if (transaction.necessity_level_override) {
    return { level: transaction.necessity_level_override, source: 'override' }
  }
  const { level } = categoryNecessity(byId.get(transaction.category_id ?? ''), byId)
  return { level, source: level ? 'category' : null }
}

/** Active expense categories that resolve to no level — the "da classificare" count. */
export function unclassifiedExpenseCategories(categories: Category[] | undefined): Category[] {
  const byId = indexById(categories)
  return (categories ?? []).filter(
    (c) => c.type === 'expense' && !c.deleted_at && categoryNecessity(c, byId).level === null,
  )
}

/** Parents in name order, each followed by its children. */
export function categoryTree(categories: Category[], type?: CategoryType): { parent: Category; children: Category[] }[] {
  const scoped = categories.filter((c) => !c.deleted_at && (!type || c.type === type))
  const byName = (a: Category, b: Category) => a.name.localeCompare(b.name, 'it')
  return scoped
    .filter((c) => c.parent_id === null)
    .sort(byName)
    .map((parent) => ({
      parent,
      children: scoped.filter((c) => c.parent_id === parent.id).sort(byName),
    }))
}

/** "Casa › Affitto" */
export function categoryPath(category: Category | undefined, byId: Map<string, Category>): string {
  if (!category) return ''
  const parent = category.parent_id ? byId.get(category.parent_id) : undefined
  return parent ? `${parent.name} › ${category.name}` : category.name
}
