import { apiDelete, apiGet, apiPost, apiPut } from './client'
import type { MenuData } from '@/types'

// 周菜单: 复用 meal-planner 现有接口 (GET /current + 单餐操作)。

export function getCurrentMenu(): Promise<MenuData> {
  return apiGet<MenuData>('/api/menus/current')
}

/** 按冰箱现有食材重排本周 (同步, 不调 LLM), 保留锁定的餐次 */
export function rebuildMenu(weekStart?: string): Promise<unknown> {
  return apiPost('/api/menus/fridge-rebuild', { force: true, week_start: weekStart ?? null })
}

/** 换一道: 留空走自动 (本地库挑 → AI 兜底) */
export function replaceMenuItem(menuId: number, itemId: number): Promise<MenuData> {
  return apiPut<MenuData>(`/api/menus/${menuId}/items/${itemId}/replace`, {})
}

export function setLockMenuItem(menuId: number, itemId: number, locked: boolean): Promise<unknown> {
  return apiPut(`/api/menus/${menuId}/items/${itemId}/${locked ? 'lock' : 'unlock'}`, {})
}

export function markCookedMenuItem(menuId: number, itemId: number): Promise<{
  item_id: number
  already_cooked: boolean
  consumed: { ingredient_name: string; quantity: number; unit: string }[]
  missing: { ingredient_name: string; deficit: number; unit: string }[]
}> {
  return apiPut(`/api/menus/${menuId}/items/${itemId}/cooked`, {})
}

export function undoCookedMenuItem(menuId: number, itemId: number): Promise<unknown> {
  return apiDelete(`/api/menus/${menuId}/items/${itemId}/cooked`)
}
