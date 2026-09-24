/**
 * H5 端的用户设置持久化
 *
 * 小程序有 Taro 的 storage, H5 没有 —— 这里用 localStorage 补上同一层。
 * 业务规则全部复用 shared/user-settings.ts 的纯函数, 这一层只负责读写,
 * 保证两端对"引导该不该弹"的判断完全一致。
 */
import {
  DEFAULT_USER_SETTINGS,
  markGuideAutoShown,
  migrateUserSettings,
  shouldAutoShowGuide,
  shouldAutoShowGuideNow,
  type UserSettings,
} from '@shared/user-settings'

const STORAGE_KEY = 'meal-planner:user-settings:v1'
const LEGACY_KEY = 'meal-planner:onboarded'

export function readUserSettings(): UserSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return migrateUserSettings(JSON.parse(raw))
  } catch {
    // 读到脏数据就当没配过, 别让一个坏 JSON 把引导卡死
  }
  // 老版本只存了一个布尔: 完成过引导 = true
  const legacy = localStorage.getItem(LEGACY_KEY)
  const settings = migrateUserSettings(null, legacy === '1' || legacy === 'true')
  if (legacy) localStorage.removeItem(LEGACY_KEY)
  return settings
}

export function writeUserSettings(settings: UserSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // 隐私模式下 localStorage 会抛, 引导只是不记住而已, 不影响使用
  }
}

export function updateUserSettings(patch: Partial<UserSettings>): UserSettings {
  const next = { ...readUserSettings(), ...patch, version: DEFAULT_USER_SETTINGS.version }
  writeUserSettings(next)
  return next
}

export function markGuideCompleted(): void {
  const current = readUserSettings()
  writeUserSettings({
    ...current,
    guide: { ...current.guide, completed: true },
  })
}

export { shouldAutoShowGuide, shouldAutoShowGuideNow, markGuideAutoShown }
