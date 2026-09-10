/**
 * 文案字典 - H5 与小程序共用, 保证两端用词完全一致
 */

export const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'] as const

/** 星期条里的单字, 窄屏也能撑开 */
export const WEEKDAY_SHORT = ['一', '二', '三', '四', '五', '六', '日'] as const

export const MEAL_LABELS: Record<string, string> = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
}

export const MEAL_ORDER = ['breakfast', 'lunch', 'dinner'] as const

export const MENU_STATUS_LABELS: Record<string, string> = {
  draft: '待确认',
  confirmed: '已确认',
  active: '进行中',
  completed: '已完成',
}

export const DAY_TYPE_LABELS: Record<string, string> = {
  weekday: '工作日',
  weekend: '周末',
}

/** 采购清单分类的展示顺序 */
export const CATEGORY_ORDER = ['蔬菜', '肉蛋', '水产', '豆制品', '主食', '调味', '干货', '其他']

export const GENERATION_STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  running: 'AI 正在生成',
  succeeded: '已生成',
  failed: '生成失败',
}

export function weekdayLabel(index: number): string {
  return WEEKDAY_LABELS[index] ?? ''
}

export function mealLabel(mealType: string): string {
  return MEAL_LABELS[mealType] ?? mealType
}

/** 分类排序: 已知分类按 CATEGORY_ORDER, 未知分类排最后 */
export function categoryRank(category: string): number {
  const index = CATEGORY_ORDER.indexOf(category)
  return index === -1 ? CATEGORY_ORDER.length : index
}
