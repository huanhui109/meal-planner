/**
 * 餐次级操作 (换一道 / 锁定 / 标记已做)
 *
 * 两处页面都用, 所以抽出来。小程序没有自定义弹窗组件时, `Taro.showModal` 的
 * 可编辑模式 (editable: true) 是最省事也最"原生"的输入方式。
 */
import Taro from '@tarojs/taro'

import type { MenuDetail } from '@shared/types'

import { lockMenuItem, markItemCooked, replaceMenuItem, undoMarkItemCooked, unlockMenuItem } from './api'
import { toast } from './nav'

/** 微信扩展过的 showModal: editable 与返回的 content 不在 Taro 类型里 */
interface EditableModalResult {
  confirm: boolean
  content?: string
}

/** 换一道: 让用户输个菜名, 后端负责重算食材与成本 */
export async function askReplaceRecipe(
  menu: MenuDetail,
  itemId: number,
  currentName: string,
): Promise<boolean> {
  const modal = (await Taro.showModal({
    title: '换一道',
    editable: true,
    placeholderText: `现在: ${currentName}, 想换成?`,
    confirmText: '就它了',
    cancelText: '算了',
  } as never)) as unknown as EditableModalResult
  if (!modal.confirm) return false
  const name = (modal.content || '').trim()
  if (!name) {
    toast('没有输入菜名')
    return false
  }
  await replaceMenuItem(menu.id, itemId, { recipe_name: name })
  toast('已换好', 'success')
  return true
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
