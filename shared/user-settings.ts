/**
 * 用户设置（本地偏好）— H5 与小程序共用
 *
 * 这里是"用户自己能改的开关"的唯一真源, 与后端的业务偏好 (家庭/忌口/预算) 分开:
 *   - 业务偏好存在服务端, 换设备要跟着账号走 → `shared/types.ts` 的 UserPreferenceSummary
 *   - 本地设置只影响这台设备上的展示行为, 不值得为它加接口 → 放这里
 *
 * 目前只有一组: **新手指引 (guide)**。
 *
 * 历史包袱: 之前引导状态是一个孤立的布尔标记
 *   - 小程序: `mp_onboarded` (lib/session.ts)
 *   - 语义是"走过引导没走过", 写死在代码里: 没走过就 reLaunch 到引导页, 用户没有选择权
 * 现在收敛成结构化的 `UserSettings.guide`, 由用户在「我的 → 用户信息」里自己开关、
 * 自己选展示时机。迁移规则见 `migrateUserSettings()`。
 */

/** 展示时机: 完成后不再自动展示 / 每次冷启动都展示 / 从不自动展示 */
export type GuideShowMode = 'once' | 'always' | 'never'

export interface GuideSettings {
  /** 总开关。关掉后不再自动展示, 设置里的「重新查看引导」也一并隐藏 */
  enabled: boolean
  /** 什么时候自动展示 */
  showMode: GuideShowMode
  /** 是否已经完整走过一次引导 (once 模式下用它判断是否还要展示) */
  completed: boolean
}

export interface UserSettings {
  /** 结构版本, 结构变了就 +1, 配合 migrateUserSettings 做升级 */
  version: number
  guide: GuideSettings
}

export const USER_SETTINGS_VERSION = 1

export const GUIDE_SHOW_MODE_LABELS: Record<GuideShowMode, string> = {
  once: '仅首次',
  always: '每次启动',
  never: '不自动展示',
}

export const DEFAULT_USER_SETTINGS: UserSettings = {
  version: USER_SETTINGS_VERSION,
  guide: {
    // 新用户默认开: 不给引导, 第一次进来大概率不知道干嘛
    enabled: true,
    // once = 走完一次就不再打扰; 想再看可以去设置里点「重新查看引导」
    showMode: 'once',
    completed: false,
  },
}

const isGuideShowMode = (v: unknown): v is GuideShowMode =>
  v === 'once' || v === 'always' || v === 'never'

/** 补齐缺失字段: 老版本 / 被手改过的 storage 都能安全读出来 */
function normalizeGuide(raw: unknown): GuideSettings {
  const g = (raw ?? {}) as Partial<GuideSettings>
  return {
    enabled: typeof g.enabled === 'boolean' ? g.enabled : DEFAULT_USER_SETTINGS.guide.enabled,
    showMode: isGuideShowMode(g.showMode) ? g.showMode : DEFAULT_USER_SETTINGS.guide.showMode,
    completed:
      typeof g.completed === 'boolean' ? g.completed : DEFAULT_USER_SETTINGS.guide.completed,
  }
}

/**
 * 迁移 / 规范化
 *
 * @param raw storage 里读到的原始值 (可能是任意类型, 别信它)
 * @param legacyOnboarded 老的孤立标记 `mp_onboarded` 的值; 传 undefined 表示没有这个老 key
 *
 * 老用户迁移规则 (保证"已有用户不受影响"):
 *   - 老标记 = true (已经走过引导) → `completed: true`, 开关保持开启
 *     → 因为默认 showMode 是 once, 所以**不会再自动弹引导**, 和老行为一致;
 *       但用户随时可以在设置里改成「每次启动」或点「重新查看引导」
 *   - 没有老标记 (新用户, 或老版本里没走完引导) → 走默认值, 首次会展示引导
 */
export function migrateUserSettings(raw: unknown, legacyOnboarded?: unknown): UserSettings {
  const source = (raw ?? {}) as Partial<UserSettings>
  if (raw && typeof raw === 'object' && source.guide) {
    return { version: USER_SETTINGS_VERSION, guide: normalizeGuide(source.guide) }
  }
  if (legacyOnboarded === true || legacyOnboarded === 'true') {
    return {
      version: USER_SETTINGS_VERSION,
      guide: { ...DEFAULT_USER_SETTINGS.guide, completed: true },
    }
  }
  return { ...DEFAULT_USER_SETTINGS, guide: { ...DEFAULT_USER_SETTINGS.guide } }
}

/** 这次启动要不要自动展示引导 */
export function shouldAutoShowGuide(settings: UserSettings): boolean {
  const { guide } = settings
  if (!guide.enabled) return false
  if (guide.showMode === 'always') return true
  if (guide.showMode === 'never') return false
  // once: 没走完才展示
  return !guide.completed
}

/**
 * 「这次进首页要不要自动弹引导」—— 在 shouldAutoShowGuide 之上再加一层
 * **一次启动最多弹一次** 的闸门。
 *
 * 少了这层会出死循环: 用户在引导里答完 3 题点「进饭决」回首页, 首页的守卫一判
 * "该展示引导" 就把人推回引导页, 于是永远进不去主页 —— showMode 为 always
 * (每次启动) 时必然触发, once 模式下只要 completed 没写成功也会触发。
 *
 * 用模块级变量表达"一次启动"就够了, 不需要 storage:
 *   - H5: 刷新页面会重建 JS 上下文
 *   - 小程序: 冷启动重建 JS 上下文; 而引导页 reLaunch 回首页**不会**重建,
 *     正好把上面那条回弹路径挡住
 *
 * ⚠ 判断与标记必须分成两个函数, 不能合成一个"抢名额"函数:
 *   H5 开了 StrictMode, 组件渲染期会被 React 双调用。若判断顺手把名额消耗掉,
 *   第二次渲染就返回 false, 重定向反而永远不触发 (比回弹更糟 —— 引导彻底不弹了)。
 *   所以 shouldAutoShowGuideNow 是纯读, 只有真的执行跳转时才调 markGuideAutoShown()。
 */
let autoShownThisLaunch = false

export function hasAutoShownGuideThisLaunch(): boolean {
  return autoShownThisLaunch
}

/** 真的把用户送去引导页之后调用一次, 本次启动内不再自动弹 */
export function markGuideAutoShown(): void {
  autoShownThisLaunch = true
}

/** 仅供测试: 重置闸门, 模拟"冷启动" */
export function resetGuideAutoShowForTest(): void {
  autoShownThisLaunch = false
}

/**
 * 首页守卫用的最终判断: 规则允许 + 本次启动还没自动弹过。
 * 纯函数, 可以放心在渲染期调用 (StrictMode 双调用结果一致)。
 */
export function shouldAutoShowGuideNow(settings: UserSettings): boolean {
  return shouldAutoShowGuide(settings) && !autoShownThisLaunch
}
