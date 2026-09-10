import apiClient, { unwrap } from './client'
import type {
  ConsumeResult,
  GenerateAccepted,
  GenerationTask,
  MenuDetail,
  ShoppingList,
} from '../types'

/** 本周周一 (本地时区, 避免 toISOString 的 UTC 偏移) */
export function currentWeekStart(base: Date = new Date()): string {
  const date = new Date(base)
  const weekday = (date.getDay() + 6) % 7
  date.setDate(date.getDate() - weekday)
  return formatDate(date)
}

export function formatDate(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

export function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00`)
  date.setDate(date.getDate() + days)
  return formatDate(date)
}

/** 提交生成任务 (同一周已有草稿会直接复用) */
export const generateMenu = (weekStart?: string, force = false) =>
  unwrap<GenerateAccepted>(
    apiClient.post('/menus/generate', {
      week_start: weekStart || currentWeekStart(),
      force,
    }),
  )

/** 轮询生成任务 */
export const getGenerationTask = (taskId: number) =>
  unwrap<GenerationTask>(apiClient.get(`/menus/generation-tasks/${taskId}`))

/** 当前进行中的菜单 */
export const getCurrentMenu = () => unwrap<MenuDetail>(apiClient.get('/menus/current'))

/** 菜单详情 */
export const getMenu = (menuId: number) => unwrap<MenuDetail>(apiClient.get(`/menus/${menuId}`))

/** 确认菜单 */
export const confirmMenu = (menuId: number) =>
  unwrap<{ menu_id: number; status: string }>(apiClient.post(`/menus/${menuId}/confirm`))

/** 采购清单 */
export const getShoppingList = (menuId: number) =>
  unwrap<ShoppingList>(apiClient.get(`/menus/${menuId}/shopping-list`))

/** 替换某一餐的菜品 */
export const replaceMenuItem = (
  menuId: number,
  itemId: number,
  body: {
    recipe_name: string
    calories?: number
    cook_minutes?: number
    protein_g?: number
    carb_g?: number
    fat_g?: number
    steps?: string
  },
) => unwrap<MenuDetail>(apiClient.put(`/menus/${menuId}/items/${itemId}/replace`, body))

export const lockMenuItem = (menuId: number, itemId: number) =>
  unwrap<{ item_id: number; is_locked: boolean }>(
    apiClient.put(`/menus/${menuId}/items/${itemId}/lock`),
  )

export const unlockMenuItem = (menuId: number, itemId: number) =>
  unwrap<{ item_id: number; is_locked: boolean }>(
    apiClient.put(`/menus/${menuId}/items/${itemId}/unlock`),
  )

/** 标记已做并扣减库存 */
export const markItemCooked = (menuId: number, itemId: number) =>
  unwrap<ConsumeResult>(apiClient.put(`/menus/${menuId}/items/${itemId}/cooked`))

/** 撤销「标记已做」: 库存还原, 消耗流水删除 */
export const undoMarkCooked = (menuId: number, itemId: number) =>
  unwrap<{ item_id: number; restored: Array<{ ingredient_name: string; quantity: number; unit: string }>; skipped: number }>(
    apiClient.delete(`/menus/${menuId}/items/${itemId}/cooked`),
  )
