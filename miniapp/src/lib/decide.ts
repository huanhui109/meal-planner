/**
 * 饭决决策 (小程序端)
 *
 * 与 H5 的 stores/useDecideStore.ts 是同一套行为, 只是载体不同:
 * H5 用 zustand, 小程序没有全局 store 依赖, 这里用模块级缓存 + Taro storage。
 *
 * 三条必须守住的行为:
 *   1. 断网 / 请求失败 → 落 decideOffline(), 永远有答案 (需求 7)
 *   2. 连续决策计数 → 到阈值弹「别纠结了，我替你倔一回。」(需求 4)
 *   3. 决策历史写本地, 离线去重靠它 (需求 5)
 */
import Taro from '@tarojs/taro'
import {
  decideOffline,
  resolveMealSlot,
  toDateKey,
  type DecideHistoryItem,
  type OfflineProfile,
} from '@shared/decide'
import type {
  DecideProfile as DecideProfilePayload,
  DecisionResult,
  MealSlot,
} from '@shared/types'
import { http } from './request'
import { applyServerLayoutVersion } from './layout-version'

const HISTORY_KEY = 'mp_decide_history:v1'
const PROFILE_KEY = 'mp_decide_profile:v1'
const ROUND_KEY = 'mp_decide_round:v1'
const RESULT_KEY = 'mp_decide_last:v1'
/**
 * 倔强阈值**不再写死**: 深夜 2 次 / 工作日 3 次 / 周末 5 次, 取 shared/decide-context.ts
 * 的 stubbornAfter()。一刀切锁 3 次, 对"在配一桌菜"的周末用户是负体验。
 * 这里保留旧常量只是为了不给其它调用方制造 break change —— 结果卡一律走 stubbornAfter()。
 */
export const STUBBORN_AFTER = 3

/**
 * /decide 响应里服务端下发的灰度版本。DecisionResult 类型还没声明这个字段,
 * 这里按"可能没有"读出来交给 lib/layout-version 存起来给埋点用。
 */
function captureLayoutVersion(result: unknown): void {
  const value = (result as { layout_version?: unknown } | null)?.layout_version
  if (value !== undefined) applyServerLayoutVersion(value)
}

/** 模块级缓存: 跨页面(引导 → 首页)传递刚决策出的结果, 避免再请求一次 */
let cached: DecisionResult | null = null

export function peekResult(): DecisionResult | null {
  return cached
}

export function setResult(result: DecisionResult | null): void {
  cached = result
  try {
    if (result) Taro.setStorageSync(RESULT_KEY, result)
    else Taro.removeStorageSync(RESULT_KEY)
  } catch {
    // 存不下不影响当次使用
  }
}

export function readCachedResult(): DecisionResult | null {
  if (cached) return cached
  try {
    const raw = Taro.getStorageSync(RESULT_KEY)
    if (raw && typeof raw === 'object') cached = raw as DecisionResult
  } catch {
    cached = null
  }
  return cached
}

function readHistory(): DecideHistoryItem[] {
  try {
    const raw = Taro.getStorageSync(HISTORY_KEY)
    return Array.isArray(raw) ? (raw as DecideHistoryItem[]) : []
  } catch {
    return []
  }
}

function pushHistory(result: DecisionResult): void {
  try {
    const next: DecideHistoryItem[] = [
      {
        name: result.dish.name,
        category: result.dish.category,
        cuisine: result.dish.cuisine,
        main: result.dish.main_ingredient,
        date: toDateKey(new Date()),
      },
      ...readHistory(),
    ].slice(0, 30)
    Taro.setStorageSync(HISTORY_KEY, next)
  } catch {
    // 忽略
  }
}

function readProfile(): OfflineProfile {
  try {
    const raw = Taro.getStorageSync(PROFILE_KEY)
    if (raw && typeof raw === 'object') return raw as OfflineProfile
  } catch {
    // 忽略
  }
  return { cuisines: [], spiceLevel: 2, avoid: [], cookCap: 60 }
}

/** 拉一次决策档案并缓存, 供离线决策使用 */
export async function syncProfile(): Promise<void> {
  try {
    const profile = await http.get<DecideProfilePayload>('/decide/profile')
    const offline: OfflineProfile = {
      cuisines: profile.cuisines || [],
      spiceLevel: profile.spice_level ?? 2,
      // 忌口与过敏同等对待: 两者都是"不能出现"
      avoid: [...(profile.avoid || []), ...(profile.allergens || [])],
      cookCap: profile.cook_cap || 60,
      mealBudget: profile.meal_budget ?? null,
    }
    Taro.setStorageSync(PROFILE_KEY, offline)
  } catch {
    // 拿不到就用默认值, 离线场景仍然能出结果
  }
}

function offlineResult(outcome: NonNullable<ReturnType<typeof decideOffline>>): DecisionResult {
  const d = outcome.dish
  return {
    id: 0,
    dish: {
      recipe_id: null,
      name: d.n,
      cuisine: d.cu,
      category: d.ca,
      cover_text: d.cv,
      cook_minutes: d.cm,
      calories: d.kcal,
      difficulty: d.df,
      main_ingredient: d.mi,
      ingredients: [...d.ig],
      steps: [...d.st],
    },
    reason: outcome.reason,
    meal_slot: outcome.mealSlot,
    meal_slot_label: '',
    source: 'offline',
    weather: {},
    advice: null,
    relaxed: outcome.relaxed,
    decided_at: new Date().toISOString(),
  }
}

/**
 * 决策一次。断网自动落离线。
 *
 * @param utterance 一句口语诉求(可空)。后端 DecideRequest 有这个字段, 给了才会
 *   据此收敛候选; 空串与不传完全等价 —— "不说直接按"是产品承诺。
 * @returns { result, offline }
 */
export async function rollDecide(
  slot?: MealSlot,
  exclude: string[] = [],
  utterance?: string,
): Promise<{ result: DecisionResult | null; offline: boolean }> {
  try {
    const result = await http.post<DecisionResult>('/decide', {
      meal_slot: slot ?? resolveMealSlot(),
      exclude,
      ...(utterance ? { utterance } : {}),
    })
    captureLayoutVersion(result)
    setResult(result)
    pushHistory(result)
    bumpRound()
    return { result, offline: false }
  } catch {
    const outcome = decideOffline(
      { profile: readProfile(), history: readHistory(), exclude },
      new Date(),
    )
    if (!outcome) return { result: null, offline: true }
    const result = offlineResult(outcome)
    setResult(result)
    pushHistory(result)
    bumpRound()
    return { result, offline: true }
  }
}

export async function loadLastDecision(): Promise<DecisionResult | null> {
  if (cached) return cached
  try {
    const result = await http.get<DecisionResult | null>('/decide/last')
    if (result) setResult(result)
    return result ?? null
  } catch {
    return readCachedResult()
  }
}

export async function sendDecideFeedback(decisionId: number, liked: boolean): Promise<void> {
  if (!decisionId) return
  try {
    await http.post(`/decide/${decisionId}/feedback`, { liked })
  } catch {
    // 反馈失败不影响主流程
  }
}

/** 连续决策计数。按天重置 —— 昨天的纠结不该影响今天 */
export function getRound(): number {
  try {
    const raw = Taro.getStorageSync(ROUND_KEY) as { date?: string; count?: number } | null
    const today = toDateKey(new Date())
    if (raw && raw.date === today) return raw.count ?? 0
  } catch {
    // 忽略
  }
  return 0
}

function bumpRound(): void {
  try {
    Taro.setStorageSync(ROUND_KEY, { date: toDateKey(new Date()), count: getRound() + 1 })
  } catch {
    // 忽略
  }
}

export function resetRound(): void {
  try {
    Taro.setStorageSync(ROUND_KEY, { date: toDateKey(new Date()), count: 0 })
  } catch {
    // 忽略
  }
}
