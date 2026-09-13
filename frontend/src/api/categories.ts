import { apiClient } from './client'
import type { Category, CategoryCreatePayload, CategoryUpdatePayload } from '@/types'

export async function listCategories(): Promise<Category[]> {
  const { data } = await apiClient.get<Category[]>('/categories')
  return data
}

export async function createCategory(payload: CategoryCreatePayload): Promise<Category> {
  const { data } = await apiClient.post<Category>('/categories', payload)
  return data
}

export async function updateCategory(id: string, payload: CategoryUpdatePayload): Promise<Category> {
  const { data } = await apiClient.patch<Category>(`/categories/${id}`, payload)
  return data
}

export async function deleteCategory(id: string): Promise<void> {
  await apiClient.delete(`/categories/${id}`)
}
