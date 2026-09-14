import { useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { GripVerticalIcon, PencilIcon, PlusIcon, TrashIcon } from '@/components/ui/Icon'
import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useUpdateCategory,
} from '@/hooks/useCategories'
import type { Category, CategoryType, NecessityLevel } from '@/types'

const TYPE_LABELS: Record<CategoryType, string> = {
  expense: 'Spese',
  income: 'Entrate',
  transfer: 'Trasferimenti',
}

const NECESSITY_LABELS: Record<NecessityLevel, string> = {
  primary: 'Primario',
  useful: 'Utile',
  discretionary: 'Accessorio',
}

// Inherited level of a subcategory: its own if set, otherwise its parent's.
// Mirrors the backend's COALESCE chain so the "Eredita" option can name the
// level the user will actually get.
function inheritedLevel(category: Category, categories: Category[]): NecessityLevel | null {
  if (category.necessity_level) return category.necessity_level
  if (!category.parent_id) return null
  return categories.find((c) => c.id === category.parent_id)?.necessity_level ?? null
}

// A <select> inside a draggable <li> would start a drag on mousedown, so the
// wrapper cancels it — the row stays draggable by its name and grip handle.
function NecessitySelect({
  category,
  categories,
  onChange,
  disabled,
}: {
  category: Category
  categories: Category[]
  onChange: (level: NecessityLevel | null) => void
  disabled: boolean
}) {
  const inherited = category.parent_id ? inheritedLevel(category, categories) : null
  const emptyLabel =
    category.parent_id && inherited
      ? `Eredita (${NECESSITY_LABELS[inherited]})`
      : 'Non classificato'

  return (
    <span draggable={false} onDragStart={(e) => e.preventDefault()}>
      <select
        value={category.necessity_level ?? ''}
        disabled={disabled}
        onChange={(e) => onChange((e.target.value || null) as NecessityLevel | null)}
        aria-label={`Livello di necessità di ${category.name}`}
        title="Livello di necessità"
        className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:opacity-50"
      >
        <option value="">{emptyLabel}</option>
        {(Object.keys(NECESSITY_LABELS) as NecessityLevel[]).map((level) => (
          <option key={level} value={level}>
            {NECESSITY_LABELS[level]}
          </option>
        ))}
      </select>
    </span>
  )
}

function IncomeBaseToggle({
  category,
  onChange,
  disabled,
}: {
  category: Category
  onChange: (excluded: boolean) => void
  disabled: boolean
}) {
  return (
    <label
      className="flex shrink-0 items-center gap-1.5 text-xs text-slate-500"
      title="Le entrate di questa categoria non contano nella base di calcolo del piano (es. rimborsi, storni)"
    >
      <input
        type="checkbox"
        checked={category.excluded_from_income_base}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-slate-300 text-slate-800 focus:ring-slate-500"
      />
      Esclusa dal reddito
    </label>
  )
}

// A subcategory drag carries its id under a type-specific MIME key, so a
// root category only accepts drops of subcategories of its own type — the
// backend would reject a cross-type move anyway (same rule as creation),
// this just gives the right "not allowed" cursor instead of a failed request.
function dragMimeType(type: CategoryType): string {
  return `application/x-category-${type}`
}

function buildTree(categories: Category[], type: CategoryType) {
  const roots = categories.filter((c) => c.type === type && c.parent_id === null)
  return roots.map((root) => ({
    root,
    children: categories.filter((c) => c.parent_id === root.id),
  }))
}

function CategoryTypeSection({ type, categories }: { type: CategoryType; categories: Category[] }) {
  const createCategory = useCreateCategory()
  const updateCategory = useUpdateCategory()
  const deleteCategory = useDeleteCategory()

  const [newRootName, setNewRootName] = useState('')
  const [addingChildTo, setAddingChildTo] = useState<string | null>(null)
  const [newChildName, setNewChildName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dropTargetId, setDropTargetId] = useState<string | null>(null)

  const roots = categories.filter((c) => c.type === type && c.parent_id === null)
  const tree = buildTree(categories, type)

  async function handleCreateRoot(e: FormEvent) {
    e.preventDefault()
    if (!newRootName.trim()) return
    await createCategory.mutateAsync({ name: newRootName.trim(), type, parent_id: null })
    setNewRootName('')
  }

  async function handleCreateChild(parentId: string) {
    if (!newChildName.trim()) return
    await createCategory.mutateAsync({ name: newChildName.trim(), type, parent_id: parentId })
    setNewChildName('')
    setAddingChildTo(null)
  }

  function startEditing(category: Category) {
    setEditingId(category.id)
    setEditingName(category.name)
  }

  async function saveEditing(id: string) {
    if (!editingName.trim()) return
    await updateCategory.mutateAsync({ id, payload: { name: editingName.trim() } })
    setEditingId(null)
  }

  async function handleNecessityChange(id: string, level: NecessityLevel | null) {
    await updateCategory.mutateAsync({ id, payload: { necessity_level: level } })
  }

  async function handleIncomeBaseChange(id: string, excluded: boolean) {
    await updateCategory.mutateAsync({ id, payload: { excluded_from_income_base: excluded } })
  }

  async function handleMove(childId: string, newParentId: string) {
    if (!newParentId) return
    await updateCategory.mutateAsync({ id: childId, payload: { parent_id: newParentId } })
  }

  function handleDragStart(child: Category) {
    return (e: DragEvent<HTMLLIElement>) => {
      e.dataTransfer.setData(dragMimeType(child.type), child.id)
      e.dataTransfer.effectAllowed = 'move'
      setDraggingId(child.id)
    }
  }

  function handleDragEnd() {
    setDraggingId(null)
    setDropTargetId(null)
  }

  function handleRootDragOver(e: DragEvent<HTMLLIElement>) {
    if (e.dataTransfer.types.includes(dragMimeType(type))) {
      e.preventDefault()
    }
  }

  function handleRootDragEnter(rootId: string) {
    return (e: DragEvent<HTMLLIElement>) => {
      if (e.dataTransfer.types.includes(dragMimeType(type))) {
        setDropTargetId(rootId)
      }
    }
  }

  function handleRootDragLeave(rootId: string) {
    return (e: DragEvent<HTMLLIElement>) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
        setDropTargetId((current) => (current === rootId ? null : current))
      }
    }
  }

  function handleRootDrop(rootId: string) {
    return (e: DragEvent<HTMLLIElement>) => {
      e.preventDefault()
      const childId = e.dataTransfer.getData(dragMimeType(type))
      setDraggingId(null)
      setDropTargetId(null)
      if (!childId) return
      const dragged = categories.find((c) => c.id === childId)
      if (!dragged || dragged.parent_id === rootId) return
      handleMove(childId, rootId)
    }
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

  return (
    <div className="rounded-lg bg-white shadow-sm">
      <div className="border-b border-slate-100 px-6 py-4">
        <h2 className="text-lg font-semibold text-slate-800">{TYPE_LABELS[type]}</h2>
      </div>

      <form onSubmit={handleCreateRoot} className="flex gap-2 border-b border-slate-100 px-6 py-4">
        <input
          value={newRootName}
          onChange={(e) => setNewRootName(e.target.value)}
          placeholder="Nuova categoria"
          className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        <button
          type="submit"
          disabled={createCategory.isPending}
          aria-label="Aggiungi"
          title="Aggiungi"
          className="rounded-md bg-slate-800 p-2 text-white hover:bg-slate-700 disabled:opacity-50"
        >
          <PlusIcon />
        </button>
      </form>

      {roots.length === 0 && <p className="px-6 py-4 text-sm text-slate-500">Nessuna categoria ancora.</p>}

      <ul className="divide-y divide-slate-100">
        {tree.map(({ root, children }) => {
          return (
            <li
              key={root.id}
              onDragOver={handleRootDragOver}
              onDragEnter={handleRootDragEnter(root.id)}
              onDragLeave={handleRootDragLeave(root.id)}
              onDrop={handleRootDrop(root.id)}
              className={`px-6 py-4 transition-colors ${
                dropTargetId === root.id ? 'bg-slate-50 ring-2 ring-inset ring-slate-300' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                {editingId === root.id ? (
                  <div className="flex flex-1 items-center gap-2">
                    <input
                      value={editingName}
                      onChange={(e) => setEditingName(e.target.value)}
                      className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
                      autoFocus
                    />
                    <button
                      onClick={() => saveEditing(root.id)}
                      className="text-sm font-medium text-slate-800 hover:underline"
                    >
                      Salva
                    </button>
                    <button onClick={() => setEditingId(null)} className="text-sm text-slate-500 hover:underline">
                      Annulla
                    </button>
                  </div>
                ) : (
                  <p className="flex-1 text-sm font-medium text-slate-800">{root.name}</p>
                )}

                {editingId !== root.id && type === 'expense' && (
                  <NecessitySelect
                    category={root}
                    categories={categories}
                    disabled={updateCategory.isPending}
                    onChange={(level) => handleNecessityChange(root.id, level)}
                  />
                )}

                {editingId !== root.id && type === 'income' && (
                  <IncomeBaseToggle
                    category={root}
                    disabled={updateCategory.isPending}
                    onChange={(excluded) => handleIncomeBaseChange(root.id, excluded)}
                  />
                )}

                {editingId !== root.id && (
                  <div className="flex shrink-0 items-center gap-3">
                    <button
                      onClick={() => startEditing(root)}
                      aria-label="Modifica"
                      title="Modifica"
                      className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
                    >
                      <PencilIcon />
                    </button>
                    <button
                      onClick={() => setAddingChildTo(addingChildTo === root.id ? null : root.id)}
                      aria-label="Aggiungi sottocategoria"
                      title="Aggiungi sottocategoria"
                      className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
                    >
                      <PlusIcon />
                    </button>
                    <button
                      onClick={() => handleDelete(root.id, root.name)}
                      aria-label="Elimina"
                      title="Elimina"
                      className="rounded p-1.5 text-red-600 hover:bg-red-50"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                )}
              </div>

              {addingChildTo === root.id && (
                <div className="mt-3 flex gap-2 pl-4">
                  <input
                    value={newChildName}
                    onChange={(e) => setNewChildName(e.target.value)}
                    placeholder="Nome sottocategoria"
                    className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
                    autoFocus
                  />
                  <button
                    onClick={() => handleCreateChild(root.id)}
                    aria-label="Aggiungi"
                    title="Aggiungi"
                    className="rounded-md bg-slate-800 p-2 text-white hover:bg-slate-700"
                  >
                    <PlusIcon />
                  </button>
                </div>
              )}

              {children.length > 0 && (
                <ul className="mt-3 space-y-2 pl-4">
                  {children.map((child) => (
                    <li
                      key={child.id}
                      draggable={editingId !== child.id}
                      onDragStart={handleDragStart(child)}
                      onDragEnd={handleDragEnd}
                      className={`flex cursor-grab items-center justify-between gap-3 border-l-2 border-slate-100 pl-3 active:cursor-grabbing ${
                        draggingId === child.id ? 'opacity-40' : ''
                      }`}
                    >
                      {editingId === child.id ? (
                        <div className="flex flex-1 items-center gap-2">
                          <input
                            value={editingName}
                            onChange={(e) => setEditingName(e.target.value)}
                            className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
                            autoFocus
                          />
                          <button
                            onClick={() => saveEditing(child.id)}
                            className="text-sm font-medium text-slate-800 hover:underline"
                          >
                            Salva
                          </button>
                          <button onClick={() => setEditingId(null)} className="text-sm text-slate-500 hover:underline">
                            Annulla
                          </button>
                        </div>
                      ) : (
                        <span className="flex flex-1 items-center gap-1.5 text-sm text-slate-700">
                          <GripVerticalIcon className="h-3.5 w-3.5 shrink-0 text-slate-300" />
                          {child.name}
                        </span>
                      )}

                      {editingId !== child.id && type === 'expense' && (
                        <NecessitySelect
                          category={child}
                          categories={categories}
                          disabled={updateCategory.isPending}
                          onChange={(level) => handleNecessityChange(child.id, level)}
                        />
                      )}

                      {editingId !== child.id && type === 'income' && (
                        <IncomeBaseToggle
                          category={child}
                          disabled={updateCategory.isPending}
                          onChange={(excluded) => handleIncomeBaseChange(child.id, excluded)}
                        />
                      )}

                      {editingId !== child.id && (
                        <div className="flex shrink-0 items-center gap-3">
                          <button
                            onClick={() => startEditing(child)}
                            aria-label="Modifica"
                            title="Modifica"
                            className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
                          >
                            <PencilIcon />
                          </button>
                          <button
                            onClick={() => handleDelete(child.id, child.name)}
                            aria-label="Elimina"
                            title="Elimina"
                            className="rounded p-1.5 text-red-600 hover:bg-red-50"
                          >
                            <TrashIcon />
                          </button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function CategoriesPage() {
  const { data: categories, isLoading, isError } = useCategories()

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-800">Categorie</h1>

      {isLoading && <p className="text-slate-500">Caricamento...</p>}
      {isError && <p className="text-red-600">Errore nel caricamento delle categorie.</p>}

      {categories && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <CategoryTypeSection type="expense" categories={categories} />
          <CategoryTypeSection type="income" categories={categories} />
          <CategoryTypeSection type="transfer" categories={categories} />
        </div>
      )}
    </div>
  )
}
