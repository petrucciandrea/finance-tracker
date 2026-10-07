import type { SelectHTMLAttributes } from 'react'
import { categoryTree } from '@/lib/categories'
import type { Category, CategoryType } from '@/types'

interface CategorySelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  categories: Category[] | undefined
  // Scope to one type: a transaction's category must match its type.
  type?: CategoryType
  emptyLabel: string
}

/**
 * A category with active subcategories can't be assigned to a transaction
 * directly (the backend rejects it — a subcategory must be picked), so such
 * parents render as a non-selectable optgroup and only their children and
 * childless roots are options.
 */
export function CategorySelect({ categories, type, emptyLabel, className = 'field', ...props }: CategorySelectProps) {
  const tree = categoryTree(categories ?? [], type)
  return (
    <select className={className} {...props}>
      <option value="">{emptyLabel}</option>
      {tree.map(({ parent, children }) =>
        children.length > 0 ? (
          <optgroup key={parent.id} label={parent.name}>
            {children.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </optgroup>
        ) : (
          <option key={parent.id} value={parent.id}>
            {parent.name}
          </option>
        ),
      )}
    </select>
  )
}
