/**
 * 引导草稿 —— 引导页选的偏好怎么落到服务端
 *
 * 为什么要单独一个模块: 引导发生在**用户可能还没登录**的时候 (小程序先体验后登录),
 * 但偏好必须写进服务端, 否则首页 `has_preferences` 一直是 false, 引导等于白做。
 *
 * 流程:
 *   1. 引导页「开始用」→ `flushGuideDraft(draft)`
 *   2. 已登录: 直接 PUT /preferences/household + /diet
 *   3. 未登录: 存进 storage, 等 login 页登录成功后调 `flushPendingGuideDraft()` 补交
 *      (补交完自动清掉, 不会重复提交)
 */
import Taro from '@tarojs/taro'

import { saveDiet, saveHousehold } from './api'
import { isLoggedIn } from './session'

const PENDING_KEY = 'mp_guide_pending_preferences'

export interface GuideDraft {
  /** 1 / 2 / 3-4 / 5+ 四档, 存的是档位值 1|2|3|4 */
  householdSize: 1 | 2 | 3 | 4 | null
  /** 菜系偏好枚举, 与 profile 页 diet.cuisines 取值一致 */
  cuisine: 'homestyle' | 'spicy' | 'cantonese' | 'light' | 'flexible' | null
}

/** 档位 → 实际人数: 3-4 人取 3, 5+ 取 5 (后端只要一个数字, 取区间下界) */
export function householdSizeToCount(size: GuideDraft['householdSize']): number | null {
  if (size == null) return null
  if (size === 1) return 1
  if (size === 2) return 2
  if (size === 3) return 3
  return 5
}

function readPending(): GuideDraft | null {
  try {
    const raw = Taro.getStorageSync(PENDING_KEY)
    if (!raw) return null
    const parsed = typeof raw === 'string' ? (JSON.parse(raw) as GuideDraft) : (raw as GuideDraft)
    return parsed ?? null
  } catch {
    return null
  }
}

function clearPending(): void {
  try {
    Taro.removeStorageSync(PENDING_KEY)
  } catch {
    /* ignore */
  }
}

/**
 * 提交引导草稿
 *
 * @returns 'saved' 已落库 / 'pending' 未登录, 已暂存 / 'skipped' 没选完, 没什么可提交
 */
export async function flushGuideDraft(draft: GuideDraft): Promise<'saved' | 'pending' | 'skipped'> {
  const memberCount = householdSizeToCount(draft.householdSize)
  if (memberCount == null && !draft.cuisine) return 'skipped'

  if (!isLoggedIn()) {
    try {
      Taro.setStorageSync(PENDING_KEY, JSON.stringify(draft))
    } catch {
      /* ignore */
    }
    return 'pending'
  }

  try {
    if (memberCount != null) {
      await saveHousehold({
        member_count: memberCount,
        // 引导只问了人数, 其余沿用后端默认值; 用户之后可以在「我的」里细调
        meals_per_day: 3,
        kitchen_equipments: [],
        weekday_cook_minutes: 30,
        weekend_cook_minutes: 60,
      })
    }
    if (draft.cuisine) {
      await saveDiet({
        cuisines: [draft.cuisine],
        spice_level: 1,
        flavor_preference: '清淡',
        staple_preference: '米饭',
      })
    }
    return 'saved'
  } catch {
    // 提交失败也要暂存, 下次登录 / 下次进引导再试, 不能静默丢
    try {
      Taro.setStorageSync(PENDING_KEY, JSON.stringify(draft))
    } catch {
      /* ignore */
    }
    return 'pending'
  }
}

/** 登录成功后补交: 有草稿就提交并清掉, 没有就直接返回 */
export async function flushPendingGuideDraft(): Promise<boolean> {
  const draft = readPending()
  if (!draft) return false
  if (!isLoggedIn()) return false
  const result = await flushGuideDraft(draft)
  if (result === 'saved') {
    clearPending()
    return true
  }
  return false
}
