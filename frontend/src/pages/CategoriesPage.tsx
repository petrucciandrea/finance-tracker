import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useCategories, useCreateCategory, useDeleteCategory } from '@/hooks/useCategories'
import type { Category } from '@/types'

const categorySchema = z.object({
  name: z.string().min(1, 'Il nome è obbligatorio').max(100),
  type: z.enum(['expense', 'income']),
  parent_id: z.string().optional(),
})

type CategoryFormValues = z.infer<typeof categorySchema>

/**
 * Builds a flat, indented render order from the parent/child list the API
 * returns — root categories first, each immediately followed by its
 * children. Good enough for a two-level hierarchy; wouldn't scale to
 * arbitrary depth without recursion, but the backend only supports one
 * level of nesting today anyway.
 */
function sortedForDisplay(categories: Category[]): Array<{ category: Category; depth: number }> {
  const roots = categories.filter((c) => c.parent_id === null)
  const result: Array<{ category: Category; depth: number }> = []
  for (const root of roots) {
    result.push({ category: root, depth: 0 })
    const children = categories.filter((c) => c.parent_id === root.id)
    for (const child of children) {
      result.push({ category: child, depth: 1 })
    }
  }
  return result
}

export function CategoriesPage() {
  const { data: categories, isLoading, isError } = useCategories()
  const createCategory = useCreateCategory()
  const deleteCategory = useDeleteCategory()
  const [isFormOpen, setIsFormOpen] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<CategoryFormValues>({
    resolver: zodResolver(categorySchema),
    defaultValues: { type: 'expense', parent_id: '' },
  })

  const selectedType = watch('type')
  // A category's parent must share its type — the backend enforces this
  // with a 422, but filtering the dropdown here avoids the round-trip.
  const eligibleParents = (categories ?? []).filter(
    (c) => c.parent_id === null && c.type === selectedType,
  )

  async function onSubmit(values: CategoryFormValues) {
    await createCategory.mutateAsync({
      name: values.name,
      type: values.type,
      parent_id: values.parent_id || null,
    })
    reset()
    setIsFormOpen(false)
  }

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(`Eliminare la categoria "${name}"?`)) return
    try {
      await deleteCategory.mutateAsync(id)
    } catch {
      // Most likely a 409 (still has active subcategories) — the backend
      // enforces this, we just surface a plain message rather than parsing
      // the error body for this simple case.
      window.alert('Impossibile eliminare: la categoria ha ancora sottocategorie attive.')
    }
  }

  const displayList = categories ? sortedForDisplay(categories) : []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Categorie</h1>
        <button
          onClick={() => setIsFormOpen((open) => !open)}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          {isFormOpen ? 'Annulla' : 'Nuova categoria'}
        </button>
      </div>

      {isFormOpen && (
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="grid grid-cols-1 gap-4 rounded-lg bg-white p-6 shadow-sm sm:grid-cols-3"
          noValidate
        >
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-slate-700">
              Nome
            </label>
            <input
              id="name"
              {...register('name')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
            {errors.name && <p className="mt-1 text-sm text-red-600">{errors.name.message}</p>}
          </div>

          <div>
            <label htmlFor="type" className="block text-sm font-medium text-slate-700">
              Tipo
            </label>
            <select
              id="type"
              {...register('type')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="expense">Spesa</option>
              <option value="income">Entrata</option>
            </select>
          </div>

          <div>
            <label htmlFor="parent_id" className="block text-sm font-medium text-slate-700">
              Categoria padre (opzionale)
            </label>
            <select
              id="parent_id"
              {...register('parent_id')}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="">Nessuna (categoria principale)</option>
              {eligibleParents.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div className="sm:col-span-3">
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {isSubmitting ? 'Creazione...' : 'Crea categoria'}
            </button>
          </div>
        </form>
      )}

      <div className="rounded-lg bg-white shadow-sm">
        {isLoading && <p className="p-6 text-slate-500">Caricamento...</p>}
        {isError && <p className="p-6 text-red-600">Errore nel caricamento delle categorie.</p>}

        {categories && categories.length === 0 && (
          <p className="p-6 text-sm text-slate-500">Nessuna categoria ancora. Creane una per iniziare.</p>
        )}

        {displayList.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {displayList.map(({ category, depth }) => (
              <li
                key={category.id}
                className="flex items-center justify-between px-6 py-4"
                style={{ paddingLeft: `${1.5 + depth * 1.5}rem` }}
              >
                <div>
                  <p className="text-sm font-medium text-slate-800">{category.name}</p>
                  <p className="text-xs text-slate-400">
                    {category.type === 'expense' ? 'Spesa' : 'Entrata'}
                  </p>
                </div>
                <button
                  onClick={() => handleDelete(category.id, category.name)}
                  className="text-sm font-medium text-red-600 hover:underline"
                >
                  Elimina
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
