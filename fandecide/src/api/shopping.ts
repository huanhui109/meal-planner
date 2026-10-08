import { apiGet } from './client'
import type { ShoppingData } from '@/types'

// 采购清单: 由周菜单所需食材 - 冰箱库存 自动聚合 (ShoppingService.build)。

export function getShoppingList(menuId: number): Promise<ShoppingData> {
  return apiGet<ShoppingData>(`/api/menus/${menuId}/shopping-list`)
}
