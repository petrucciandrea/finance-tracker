import { apiClient } from './client'
import type { Category, CategoryCreatePayload } from '@/types'

export async function listCategories(): Promise<Category[]> {
  const { data } = await apiClient.get<Category[]>('/categories')
  return data
}

export async function createCategory(payload: CategoryCreatePayload): Promise<Category> {
  const { data } = await apiClient.post<Category>('/categories', payload)
  return data
}

export async function deleteCategory(id: string): Promise<void> {
  await apiClient.delete(`/categories/${id}`)
}
