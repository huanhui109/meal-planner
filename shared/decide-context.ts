/**
 * 首页情境判定 —— 深夜 / 周末 / 工作日三档, 全部是纯函数
 *
 * 为什么单独抽一层:
 *   这些判定同时被 store(倔强阈值)、结果卡(要不要显示「再来一个」)、
 *   首页(预算条要不要渲染)用到。散在三个文件里写三遍 `hour >= 22`,
 *   改一次漏一处就是"深夜给用户看预算已用 87%" —— 那不是提醒是添堵。
 *   抽出来还能直接跑单测 (tests/decide-context.test.ts)。
 *
 * 为什么在 shared/ 而不是某一端里:
 *   shared/ 是 H5 与小程序的唯一真源, 两端都用 `@shared/*` 别名 import。
 *   放在某一端下面, 另一端够不到, 只能把 `hour >= 22` 再手写一遍 ——
 *   那正是本文件自己在防的事。
 *
 * 时钟口径一律与 shared/decide.ts 的 resolveMealSlot() 对齐:
 *   22:00-05:00 夜宵, 否则早餐/午餐/晚餐由钟点推断。
 */
import { resolveMealSlot } from './decide'

export type ContextBucket = 'late_night' | 'weekend' | 'weekday'

/** 周末「再来一个」的窗口: 只在采购完、还来得及配一桌菜的时段给 (PRD §11-Q1 ②) */
const WEEKEND_ANOTHER_WINDOW = { start: 10, end: 20 }

/**
 * 周五过了几点就算"周末档"
 *
 * 心智上周五晚上和周六是一样的: 下班了、可以为这顿多花点时间、常常在给一桌人配菜。
 * 严格按 getDay()===0||6 判, 周五 19:20 那个"想配两个菜"的人会被 3 次锁住 ——
 * 而她不是在纠结。18:00 取的是"普遍下班时间", 再早就有通勤中的人被打进周末档。
 */
const FRIDAY_WEEKEND_START_HOUR = 18

/**
 * 倔强阈值分档 —— 取代原来的硬编码 STUBBORN_AFTER = 3
 *
 * 「换一个」在三类人嘴里是三个意思: 上班族 = 不要这个 (3 次够了);
 * 深夜 = 再快点 (耐心只有 8 秒, 2 次); 周末 = 再来一个配菜 (人家是在配一桌菜,
 * 不是在纠结, 锁 3 次是负体验)。一刀切锁 3 次, 对周末的人是负体验。
 */
export const STUBBORN_AFTER_BY_SLOT: Record<ContextBucket, number> = {
  late_night: 2,
  weekday: 3,
  weekend: 5,
}

/**
 * 深夜: 说教类信息(预算 / 营养)必须完全隐藏, 不是折叠
 *
 * ⚠ 判定**委托** resolveMealSlot(), 不在本文件里再比对一次小时数。
 *   深夜边界在这个文件里留第二份硬编码, 就等于"联网是一个口径、断网是另一个":
 *   改一次漏一处就是 22:30 联网算深夜、离线不算, 两端对同一件事给出不同答案。
 *   shared/ 的意义是两端共用同一份判定, 再抄一份就白抽了。
 *   单测因此钉的是"同口径"(resolveMealSlot 与 isLateNight 同时刻一致),
 *   而不是钉具体钟点 —— 谁改任何一侧的边界, 那条立刻红。
 */
export function isLateNight(date: Date = new Date()): boolean {
  return resolveMealSlot(date) === 'late_night'
}

/** 处在"周末心智"里: 周六/周日全天, 以及周五 18:00 之后 */
export function isWeekendMoment(date: Date = new Date()): boolean {
  const day = date.getDay()
  if (day === 0 || day === 6) return true
  return day === 5 && date.getHours() >= FRIDAY_WEEKEND_START_HOUR
}

/** 周末(含周五晚)且处在"还能配菜"的时段 —— 「再来一个」只在这里出现 */
export function isWeekendAnotherDishWindow(date: Date = new Date()): boolean {
  if (!isWeekendMoment(date)) return false
  const hour = date.getHours()
  return hour >= WEEKEND_ANOTHER_WINDOW.start && hour < WEEKEND_ANOTHER_WINDOW.end
}

/** 当前属于哪一档情境。深夜优先于周末: 周六凌晨 1 点也是"深夜", 不是"周末配菜" */
export function contextBucket(date: Date = new Date()): ContextBucket {
  if (isLateNight(date)) return 'late_night'
  if (isWeekendMoment(date)) return 'weekend'
  return 'weekday'
}

/** 当前情境下, 连续几次「换一个」之后弹倔强提示 */
export function stubbornAfter(date: Date = new Date()): number {
  return STUBBORN_AFTER_BY_SLOT[contextBucket(date)]
}

/**
 * 预算条 / 营养块能不能出现。
 * 深夜直接不渲染 —— 折叠起来也是"我知道它在那儿", 深夜的用户不需要这个提醒。
 */
export function shouldShowBudgetStrip(date: Date = new Date()): boolean {
  return !isLateNight(date)
}

/**
 * 出餐档位词 —— 取代结果卡上的精确分钟数
 *
 * ⚠ 为什么不给分钟数: recipe.cook_minutes 是规则生成的**品类基准值**, 不是实测。
 * 全库 119 道菜都是 22 分钟(荤菜默认值), 连"茶叶蛋"也是 22 分钟。
 * 把不可信的精确数字放到显眼位置 = 把数据缺陷放大成承诺破裂:
 * 用户照着"15 分钟"安排今晚, 结果不是。
 *
 * 档位依据是用户真正的相对判断(麻不麻烦), 不是绝对值:
 *   ≤15 快手 ｜ ≤30 还行 ｜ >30 要小火慢炖
 * 分钟数仍然只用于引擎内部过滤(出餐上限 / 深夜阈值), 不对外展示。
 */
export const COOK_EFFORT_THRESHOLDS = { quick: 15, normal: 30 } as const

export function cookEffortLabel(minutes: number | null | undefined): string {
  if (minutes == null || minutes <= 0) return '快手'
  if (minutes <= COOK_EFFORT_THRESHOLDS.quick) return '快手'
  if (minutes <= COOK_EFFORT_THRESHOLDS.normal) return '还行'
  return '要小火慢炖'
}

/** 状态行的钟点: 19:20 */
export function formatClock(date: Date = new Date()): string {
  const hour = `${date.getHours()}`.padStart(2, '0')
  const minute = `${date.getMinutes()}`.padStart(2, '0')
  return `${hour}:${minute}`
}

/**
 * 状态行主文案: 「19:20 · 晚餐 · 家里有 6 样」
 *
 * 餐次不给用户选, 由钟点推断 —— 状态行的作用是让"时间锚点"显性化,
 * 让用户一眼确认你没把他的晚饭当夜宵。原来那句"晚上好, 小明"占两行但零信息量。
 */
export function statusLine(input: {
  date?: Date
  fridgeCount: number | null
  mealSlotLabel: (slot: ReturnType<typeof resolveMealSlot>) => string
}): string {
  const date = input.date ?? new Date()
  const parts = [formatClock(date), input.mealSlotLabel(resolveMealSlot(date))]
  if (input.fridgeCount != null && input.fridgeCount > 0) {
    parts.push(`家里有 ${input.fridgeCount} 样`)
  }
  return parts.join(' · ')
}
