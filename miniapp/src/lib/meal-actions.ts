/**
 * 餐次级操作 (换一道 / 锁定 / 标记已做)
 *
 * 两处页面都用, 所以抽出来。小程序没有自定义弹窗组件时, `Taro.showModal` 的
 * 可编辑模式 (editable: true) 是最省事也最"原生"的输入方式。
 */
import Taro from '@tarojs/taro'

import type { MealDetail, MenuDetail } from '@shared/types'

import { lockMenuItem, markItemCooked, replaceMenuItem, undoMarkItemCooked, unlockMenuItem } from './api'
import { track } from './events'
import { toast } from './nav'

/**
 * 换一道: 后端先从本地菜谱库挑, 挑不到再让 AI 生成一道, 前端只负责结果确认。
 * 结果确认用 action sheet: 就它了 / (本地换来的话) 让 AI 再换一道 / 换回上一道。
 * 返回换好后的整份菜单, 页面据此做乐观更新, 不再整页 reload。
 */
export async function askReplaceRecipe(menu: MenuDetail, meal: MealDetail): Promise<MenuDetail | null> {
  const previous = meal.recipe

  const updated = await runReplace('正在换一道…', menu.id, meal.id, {})
  const info = updated.replacement
  const name = info?.recipe_name || '新的一道菜'
  const fromLocal = info?.source === 'local'

  type Choice = 'keep' | 'ai' | 'restore'
  const options: Array<{ label: string; choice: Choice }> = [{ label: '就它了', choice: 'keep' }]
  // 只有「本地菜谱库换来的」才给 AI 再换的入口; 已经是 AI 换的就没必要再来一次
  if (fromLocal) options.push({ label: '让 AI 再换一道', choice: 'ai' })
  if (previous?.id) options.push({ label: '换回上一道', choice: 'restore' })

  let tapIndex = 0
  try {
    const sheet = await Taro.showActionSheet({
      alertText: `已换成「${name}」\n来源: ${fromLocal ? '本地菜谱库' : 'AI 生成'}`,
      itemList: options.map((option) => option.label),
    })
    tapIndex = sheet.tapIndex
  } catch {
    return updated // 用户点空白取消, 沿用当前结果
  }

  const picked = options[tapIndex]?.choice ?? 'keep'

  if (picked === 'ai') {
    const next = await runReplace('让 AI 再换一道…', menu.id, meal.id, { force_ai: true })
    toast('已让 AI 换一道', 'success')
    return next
  }

  if (picked === 'restore' && previous?.id) {
    const restored = await runReplace('正在换回…', menu.id, meal.id, { recipe_id: previous.id })
    toast('已换回上一道')
    return restored
  }

  toast('已换好', 'success')
  return updated
}

/** 统一的 loading + 替换调用 */
async function runReplace(
  title: string,
  menuId: number,
  itemId: number,
  body: Parameters<typeof replaceMenuItem>[2],
): Promise<MenuDetail> {
  Taro.showLoading({ title, mask: true })
  try {
    return await replaceMenuItem(menuId, itemId, body)
  } finally {
    Taro.hideLoading()
  }
}

export async function toggleLock(menu: MenuDetail, itemId: number, locked: boolean): Promise<boolean> {
  if (locked) {
    await unlockMenuItem(menu.id, itemId)
    toast('已解锁')
  } else {
    await lockMenuItem(menu.id, itemId)
    toast('已锁定, 重新生成时会保留这道')
  }
  return true
}

/** 标记已做: 后端会按菜谱扣减库存, 然后把扣减/缺料结果说清楚 */
export async function markCooked(menu: MenuDetail, itemId: number): Promise<boolean> {
  track('mark_cooked', { menu_id: menu.id, item_id: itemId })
  const result = await markItemCooked(menu.id, itemId)
  if (result.already_cooked) {
    toast('这一餐之前就标记过了')
    return false
  }
  const consumed = result.consumed?.length ?? 0
  const missing = result.missing?.length ?? 0
  if (missing > 0) {
    toast(`已扣减 ${consumed} 样, ${missing} 样冰箱里不够`)
  } else {
    toast(`已扣减 ${consumed} 样库存`, 'success')
  }
  return true
}

/** 撤销「标记已做」: 库存还原, 消耗流水删除 */
export async function undoCook(menu: MenuDetail, itemId: number): Promise<boolean> {
  await undoMarkItemCooked(menu.id, itemId)
  toast('已撤销, 库存还原', 'success')
  return true
}

/** 撤销窗口时长 (毫秒) —— 页面上这段时间内餐次行里会显示「撤销」 */
export const UNDO_WINDOW_MS = 6000
