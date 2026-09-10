/**
 * "下一步该做什么"的决策函数
 *
 * H5 与小程序共用同一套规则, 所以两端的指引不会打架; 首页的 NextStepCard
 * 与各页的空状态都从这里取文案。纯函数, 可直接单测。
 */
import { formatDateRange, formatProgress, todayIso } from './format'

export type NextStepKey =
  | 'generating'
  | 'setup-preferences'
  | 'generate-menu'
  | 'confirm-menu'
  | 'shopping'
  | 'cook-today'
  | 'relax'

export interface NextStep {
  key: NextStepKey
  /** 卡片标题, 一句话说清"现在该干嘛" */
  title: string
  /** 补充说明, 解释为什么 */
  description: string
  /** 主按钮文案; null 表示这一步不需要按钮 */
  actionLabel: string | null
  /** 主按钮跳转路径; null 表示原地执行 (例如生成菜单) */
  to: string | null
  /** true 表示按钮触发的是"生成菜单"这个动作而不是跳页 */
  isGenerateAction?: boolean
}

export interface NextStepMenuLike {
  status: string
  week_start_date: string
  totals: { cooked_count: number; meal_count: number }
  days: Array<{ date: string; meals: Array<{ is_cooked: boolean }> }>
}

export interface NextStepInput {
  /** 五项偏好是否至少填了家庭信息与预算 */
  hasPreferences: boolean
  menu: NextStepMenuLike | null
  /** 采购清单里需要买的项数; 没有菜单时传 0 */
  shoppingToBuyCount: number
  /** 生成任务是否进行中 */
  generating?: boolean
  /** 覆盖"今天", 便于测试 */
  today?: string
}

export const NEXT_STEP_ROUTES = {
  preferences: '/preferences',
  menus: '/menus',
  shopping: '/shopping',
  inventory: '/inventory',
} as const

/** 今天还有几餐没做 */
export function remainingMealsToday(input: NextStepInput): number {
  if (!input.menu) return 0
  const today = input.today || todayIso()
  const day = input.menu.days.find((item) => item.date === today)
  if (!day) return 0
  return day.meals.filter((meal) => !meal.is_cooked).length
}

/** 按优先级给出唯一一条"下一步" */
export function nextStep(input: NextStepInput): NextStep {
  if (input.generating) {
    return {
      key: 'generating',
      title: 'AI 正在生成菜单',
      description: '通常需要 1-2 分钟, 可以先离开这个页面, 好了会通知你。',
      actionLabel: null,
      to: null,
    }
  }

  if (!input.hasPreferences) {
    return {
      key: 'setup-preferences',
      title: '先花 1 分钟填偏好',
      description: '家庭人数、忌口和预算决定了 AI 怎么配餐, 填完生成结果会准很多。',
      actionLabel: '去填偏好',
      to: NEXT_STEP_ROUTES.preferences,
    }
  }

  if (!input.menu) {
    return {
      key: 'generate-menu',
      title: '生成这周的营养菜谱',
      description: 'AI 会按你的偏好排好 7 天菜单, 并算好营养与预算。',
      actionLabel: '生成菜单',
      to: null,
      isGenerateAction: true,
    }
  }

  if (input.menu.status === 'draft') {
    return {
      key: 'confirm-menu',
      title: '确认这周的菜单',
      description: '可以先换掉不想吃的菜; 确认后锁定菜单, 采购清单才作数。',
      actionLabel: '去确认',
      to: NEXT_STEP_ROUTES.menus,
    }
  }

  if (input.shoppingToBuyCount > 0) {
    return {
      key: 'shopping',
      title: `有 ${input.shoppingToBuyCount} 样食材要买`,
      description: '清单已经按品类分好, 可以直接复制去下单。',
      actionLabel: '看采购清单',
      to: NEXT_STEP_ROUTES.shopping,
    }
  }

  const remaining = remainingMealsToday(input)
  if (remaining > 0) {
    const { cooked_count, meal_count } = input.menu.totals
    return {
      key: 'cook-today',
      title: '今天还有饭要做',
      description: `做完点一下「标记已做」, 冰箱库存会自动扣减。本周进度 ${formatProgress(cooked_count, meal_count)}。`,
      actionLabel: '看今天菜单',
      to: NEXT_STEP_ROUTES.menus,
    }
  }

  return {
    key: 'relax',
    title: '这周的饭都安排好了',
    description: `${formatDateRange(input.menu.week_start_date, input.menu.days[input.menu.days.length - 1]?.date ?? input.menu.week_start_date)} 的菜单已就绪, 冰箱也够用。`,
    actionLabel: '周菜单',
    to: NEXT_STEP_ROUTES.menus,
  }
}
