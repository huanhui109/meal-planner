import apiClient, { unwrap } from './client'
import type { InventoryItem, RecognitionResult } from '../types'

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

/** 按食材名模糊搜索库存 (GET /inventory?q=, 2.7.0) */
export const searchInventory = (q: string) =>
  unwrap<{ total: number; expiring_count: number; items: InventoryItem[] }>(
    apiClient.get('/inventory', { params: { q } }),
  )

/** 批量入库 (快速补常备食材, 2.7.0) */
export const bulkAddInventory = (
  items: Array<{ ingredient_name: string; quantity: number; unit: string }>,
) => unwrap<{ added: InventoryItem[] }>(apiClient.post('/inventory/bulk', { items }))

/** 改库存项的数量 / 保质期 (PUT /inventory/{id}, 2.7.0) */
export const updateInventoryItem = (
  itemId: number,
  body: { quantity?: number; expiry_date?: string | null },
) => unwrap<InventoryItem>(apiClient.put(`/inventory/${itemId}`, body))

/** 拍照识别: 只返回候选清单, 用户确认后再逐条入库 */
export const recognizeInventory = (file: File) => {
  const body = new FormData()
  body.append('file', file)
  return unwrap<RecognitionResult>(
    apiClient.post('/inventory/recognize', body, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    }),
  )
}
