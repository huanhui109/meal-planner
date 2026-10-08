import { apiDelete, apiGet, apiPost, apiPut } from './client'
import type { InventoryItem, InventoryList } from '@/types'

// 冰箱库存: 列表(可按名搜索) / 单条增删改 / 批量快速入库。

export function listInventory(q?: string): Promise<InventoryList> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ''
  return apiGet<InventoryList>(`/api/inventory${qs}`)
}

export function addInventory(opts: {
  ingredient_name: string
  quantity: number
  unit: string
  expiry_date?: string | null
}): Promise<InventoryItem> {
  return apiPost<InventoryItem>('/api/inventory', opts)
}

export function bulkAddInventory(
  items: { ingredient_name: string; quantity?: number; unit?: string }[],
): Promise<{ added: InventoryItem[] }> {
  return apiPost('/api/inventory/bulk', { items })
}

export function updateInventory(
  id: number,
  opts: { quantity?: number; expiry_date?: string | null },
): Promise<InventoryItem> {
  return apiPut<InventoryItem>(`/api/inventory/${id}`, opts)
}

export function deleteInventory(id: number): Promise<unknown> {
  return apiDelete(`/api/inventory/${id}`)
}
