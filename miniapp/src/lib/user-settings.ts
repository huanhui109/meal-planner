/**
 * 用户设置 (本地) — 小程序侧存储适配
 *
 * 结构与迁移规则在 `shared/user-settings.ts` (两端唯一真源), 这里只负责:
 *   * storage 读写 (Taro.setStorageSync)
 *   * 把老的孤立标记 `mp_onboarded` 迁移进来
 *   * 变更时通知订阅者 (useUserSettings hook)
 *
 * 为什么不再放 lib/session.ts: session.ts 管的是**登录凭据**, 而用户设置是
 * 退出登录后依然要保留的本地偏好, 混在一起会让 clearSession() 误删设置。
 */
import Taro from '@tarojs/taro'
import { useEffect, useState } from 'react'

import {
  DEFAULT_USER_SETTINGS,
  markGuideAutoShown,
  migrateUserSettings,
  shouldAutoShowGuideNow,
  USER_SETTINGS_VERSION,
  type GuideSettings,
  type GuideShowMode,
  type UserSettings,
} from '@shared/index'

// 一次启动只自动弹一次引导的闸门在 shared 里, 页面统一从这里拿, 别再直接 import shared
export { markGuideAutoShown, shouldAutoShowGuideNow }

const STORAGE_KEY = 'mp_user_settings:v1'
/** 老的孤立引导标记 (lib/session.ts 里的 ONBOARDED_KEY), 迁移完就删掉 */
const LEGACY_ONBOARDED_KEY = 'mp_onboarded'

const emitter = new (class {
  listeners = new Set<() => void>()
  on(fn: () => void) {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }
  emit() {
    for (const fn of this.listeners) fn()
  }
})()

let cached: UserSettings | null = null

function read(): UserSettings {
  let raw: unknown = null
  try {
    raw = Taro.getStorageSync(STORAGE_KEY)
    if (raw && typeof raw === 'string') raw = JSON.parse(raw) as unknown
  } catch {
    raw = null
  }

  // 老标记只读一次: 迁移成功就删掉, 避免用户在新设置里改了开关后又被老值覆盖
  let legacy: unknown
  try {
    legacy = Taro.getStorageSync(LEGACY_ONBOARDED_KEY)
  } catch {
    legacy = undefined
  }

  const settings = migrateUserSettings(raw, legacy)
  if (!raw && legacy !== undefined && legacy !== '') {
    // 首次迁移: 落盘 + 清理老 key (老用户升级后不再被两套状态干扰)
    write(settings)
    try {
      Taro.removeStorageSync(LEGACY_ONBOARDED_KEY)
    } catch {
      /* ignore */
    }
  }
  return settings
}

function write(settings: UserSettings): void {
  try {
    Taro.setStorageSync(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    /* storage 不可用 (极少数机型 / 空间满), 内存态仍然生效 */
  }
}

export function getUserSettings(): UserSettings {
  if (!cached) cached = read()
  return cached
}

/** 局部更新; 返回更新后的完整设置 */
export function updateUserSettings(patch: Partial<UserSettings>): UserSettings {
  const next: UserSettings = { ...getUserSettings(), ...patch, version: USER_SETTINGS_VERSION }
  cached = next
  write(next)
  emitter.emit()
  return next
}

export function updateGuideSettings(patch: Partial<GuideSettings>): UserSettings {
  return updateUserSettings({ guide: { ...getUserSettings().guide, ...patch } })
}

/** 引导走完一次: 记 completed, once 模式下就不会再自动弹 */
export function markGuideCompleted(): UserSettings {
  return updateGuideSettings({ completed: true })
}

export function setGuideShowMode(mode: GuideShowMode): UserSettings {
  return updateGuideSettings({ showMode: mode })
}

export function resetUserSettings(): UserSettings {
  return updateUserSettings({
    ...DEFAULT_USER_SETTINGS,
    guide: { ...DEFAULT_USER_SETTINGS.guide },
  })
}

/** 组件里订阅设置变化; 返回 [settings, updateGuide] */
export function useUserSettings(): [UserSettings, (patch: Partial<GuideSettings>) => void] {
  const [, setTick] = useState(0)
  useEffect(() => {
    // emitter.on 返回的是 Set.delete, 它返回 boolean; useEffect 要求清理函数返回 void,
    // 这里包一层, 否则 TS 报 "Type 'boolean' is not assignable to type 'void'"
    const unsubscribe = emitter.on(() => setTick((n) => n + 1))
    return () => {
      unsubscribe()
    }
  }, [])
  return [getUserSettings(), updateGuideSettings]
}
