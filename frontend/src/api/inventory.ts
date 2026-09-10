import apiClient, { unwrap } from './client'
import type { InventoryItem } from '../types'

export const listInventory = () =>
  unwrap<{ total: number; expiring_count: number; items: InventoryItem[] }>(
    apiClient.get('/inventory'),
  )

export const addInventoryItem = (body: {
  ingredient_name: string
  quantity: number
  unit: string
  expiry_date?: string | null
}) => unwrap<InventoryItem>(apiClient.post('/inventory', { ...body, source: 'manual' }))

export const deleteInventoryItem = (itemId: number) =>
  unwrap<null>(apiClient.delete(`/inventory/${itemId}`))
