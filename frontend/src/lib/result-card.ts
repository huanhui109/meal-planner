/**
 * 结果卡视图模型 —— 「这张卡上到底显示什么」的全部判断集中在这一层
 *
 * 为什么抽出来:
 *   结果卡的显示规则里塞满了"看时刻"的判断(深夜不出现热量、周末多一个「再来一个」、
 *   放宽与去重互斥)。这些规则如果写在 JSX 里, 就只能靠人眼在真机上按时间点验证 ——
 *   而"周三 23:40"这种场景没人会真的等到那个点去点。抽成纯函数后, 时刻可以注入,
 *   tests/result-card.test.ts 能在 1 秒内跑完三个验收时刻。
 *
 * 时刻一律靠参数注入, 不在函数内部 new Date():
 *   vi.useFakeTimers() 会污染整个测试环境(连 zustand 的定时器一起假掉),
 *   所以这里只接受 date 参数, 默认才取当前时间。
 */
import { clipSteps } from '@shared/decide'
import { formatKcal } from '@shared/format'
import type { DecisionResult } from '../types'
import { contextBucket, cookEffortLabel, isLateNight, isWeekendAnotherDishWindow } from '@shared/decide-context'

/**
 * ⚠ 结果卡**不显示厨具**（`tools`）—— 这里是"决定不做", 不是"还没做"。
 *
 * 三条理由, 缺一不可:
 *   1. 覆盖率 **18.2% < 30% 门槛**。按覆盖率分级法则, <30% 的字段只能加分、
 *      **不该上 UI** —— 它连上 UI 的资格都没有
 *   2. **离线池里没有 `tools` 字段** ⇒ 联网显示、断网不显示, 这本身就是双端不一致;
 *      而断网恰恰是最该兑现"永远有答案"的时刻
 *   3. 就算有值也**不构成决策信息**: 库里实际只有 `pot`(42) / `steamer`(13) /
 *      `oven`(11) / `air_fryer`(5), 全是家常厨具(库里**没有** `wok`)。
 *      告诉用户"这菜要用锅"等于什么都没说
 */

/** 结果卡上「已排除 N 道」的前缀 (契约 #17) */
export const EXCLUDED_TEXT = (n: number): string => `已排除 ${n} 道`

/** 结果卡上放宽的诚实标注 (契约 #18) —— 与「已排除 N 道」互斥且优先级更高 */
export const RELAXED_TEXT = '条件放宽了，可选项不多'

export type FootnoteKind = 'excluded' | 'relaxed' | null

export type ResultCardInput = {
  result: DecisionResult | null
  /** 注入的时刻: 测试用固定值, 线上不传 */
  now?: Date
  /** 「换一个」换掉的数量 */
  excludedCount: number
  /** 周末「再来一个」定下的数量 */
  pickedCount: number
}

export type ResultCardModel = {
  /** 3-5 步做法, 直接展开 (需求 10) */
  steps: string[]
  /** 步数从 dish.steps 真实算出 —— 这是可信的, 不像 cook_minutes */
  stepCount: number
  /** 出餐档位词: 快手 / 还行 / 要小火慢炖。⚠ 卡上不出现任何分钟数 */
  effortLabel: string
  /** 深夜不出现热量: 说教类信息在深夜是添堵, 不是提醒 */
  showKcal: boolean
  kcalText: string | null
  /**
   * 后端 relaxed 时 advice 会被写成「可选项不多，放宽了一点条件」,
   * 与放宽标注是同一件事说两遍, 所以放宽命中时把 advice 让给标注。
   */
  showAdvice: boolean
  /** 卡下方的"系统侧事实/负面信息", 一次最多一条 */
  footnote: FootnoteKind
  footnoteText: string
  /** 周末 10:00-20:00 才出现「再来一个」 */
  showAnotherDish: boolean
  /** 周末配菜定下的菜: 「今晚已定 N 道」 */
  pickedText: string | null
  bucket: ReturnType<typeof contextBucket>
}

/** 结果卡上所有"显示什么"的判断。纯函数, 时刻靠注入 */
export function buildResultCard(input: ResultCardInput): ResultCardModel {
  const { result, excludedCount, pickedCount } = input
  const now = input.now ?? new Date()
  const lateNight = isLateNight(now)
  const bucket = contextBucket(now)
  const steps = clipSteps(result?.dish.steps ?? [])

  // 放宽优先于去重: 理由已经退化成"可选项不多了, 就它吧", 这时候再写"已排除 8 道"
  // 用户只会读出"饭决品味变差了 + 系统在死磕", 两个负面叠一起比只说一个更伤。
  const relaxed = Boolean(result?.relaxed)
  const footnote: FootnoteKind = relaxed ? 'relaxed' : excludedCount > 0 ? 'excluded' : null
  const hasKcal = !lateNight && (result?.dish.calories ?? 0) > 0

  return {
    steps,
    stepCount: steps.length,
    effortLabel: cookEffortLabel(result?.dish.cook_minutes),
    showKcal: hasKcal,
    kcalText: hasKcal && result ? formatKcal(result.dish.calories) : null,
    showAdvice: Boolean(result?.advice) && !relaxed,
    footnote,
    footnoteText: footnote === 'relaxed' ? RELAXED_TEXT : EXCLUDED_TEXT(excludedCount),
    showAnotherDish: isWeekendAnotherDishWindow(now),
    pickedText: pickedCount > 0 ? `今晚已定 ${pickedCount} 道` : null,
    bucket,
  }
}
