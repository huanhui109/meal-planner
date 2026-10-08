import { apiGet, apiPost } from './client'
import type { DecisionResult, DecideRecentItem } from '@/types'

// 全部复用 meal-planner 现有决策接口, 不新增后端代码。

/** 上一次决策快照 —— 冷启动秒开结果卡, 不必重新摇一次 */
export function lastDecision(): Promise<DecisionResult | null> {
  return apiGet<DecisionResult | null>('/api/decide/last')
}

/** 决定这一顿。exclude 带上本次已拒绝的菜名, 避免「换一个」来回横跳 */
export function decide(opts: { meal_slot?: string; exclude?: string[] } = {}): Promise<DecisionResult> {
  return apiPost<DecisionResult>('/api/decide', {
    meal_slot: opts.meal_slot ?? null,
    exclude: opts.exclude ?? [],
  })
}

/** 对一次决策表态: liked=true 就这个 / false 换一个 */
export function feedback(decisionId: number, liked: boolean): Promise<{ accepted: boolean }> {
  return apiPost<{ accepted: boolean }>(`/api/decide/${decisionId}/feedback`, { liked })
}

/** 近 N 天决策记录, 给结果卡下方一条极轻的历史 */
export function recentDecisions(days = 7): Promise<DecideRecentItem[]> {
  return apiGet<DecideRecentItem[]>(`/api/decide/recent?days=${days}`)
}

/** 今日饭决「做完了」: 按结果菜谱扣减冰箱库存 (幂等) */
export function cookDecision(decisionId: number): Promise<{
  decision_id: number
  already_cooked: boolean
  no_recipe?: boolean
  consumed: { ingredient_name: string; quantity: number; unit: string }[]
  missing: { ingredient_name: string; deficit: number; unit: string }[]
}> {
  return apiPost(`/api/decide/${decisionId}/cook`)
}
