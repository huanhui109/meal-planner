/**
 * 主题 store (V2.5: 冷色 / 明亮 / 深色 + auto 跟随系统)
 *
 * 设计: 一份全局状态 + 一份 localStorage 持久化 + 一份 html[data-theme] 写入。
 * 切换时同时刷新 `<meta name="theme-color">`, 让浏览器顶栏、地址栏、手机状态栏跟上来。
 *
 * auto 模式:
 *   * 持久化 'auto' 字符串
 *   * 实际写到 html[data-theme] 的是 'cool' 或 'dark' (resolveAutoTheme 的结果)
 *   * 监听 prefers-color-scheme 变化, 实时切换 data-theme
 *
 * 迁移 (V2.4 → V2.5):
 *   * 旧 key  `meal-planner:theme`     → 新 key  `meal-planner:theme:v2`
 *   * 旧值 'dark'  → 'cool'
 *   * 旧值 'light' → 'cream'
 *   * 读到 v2 key 但值是 'dark'/'light' (老用户复制粘贴) 时也做映射
 */
import { create } from 'zustand'
import { palettes, resolveAutoTheme, type PaletteName, type ThemeName } from '@shared/index'

const STORAGE_KEY = 'meal-planner:theme:v2'
const STORAGE_KEY_LEGACY = 'meal-planner:theme'
const DEFAULT_THEME: ThemeName = 'cream'

type State = {
  theme: ThemeName
  /** 实际应用到的显式主题 (auto 模式下 = resolveAutoTheme 结果) */
  applied: PaletteName
  setTheme: (value: ThemeName) => void
}

const isValidTheme = (v: unknown): v is ThemeName =>
  v === 'cool' || v === 'cream' || v === 'dark' || v === 'auto'

/** 把老值 (dark/light) 映射到新值 (cool/cream) */
const migrateLegacyValue = (raw: string): ThemeName => {
  if (raw === 'dark') return 'cool'
  if (raw === 'light') return 'cream'
  return isValidTheme(raw) ? raw : DEFAULT_THEME
}

const readPersisted = (): ThemeName => {
  if (typeof window === 'undefined') return DEFAULT_THEME
  try {
    // 优先读 v2 新 key
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw && isValidTheme(raw)) return raw
    // 兼容老 key
    const legacy = window.localStorage.getItem(STORAGE_KEY_LEGACY)
    if (legacy) {
      const migrated = migrateLegacyValue(legacy)
      // 顺手把老 key 升级为 v2
      try {
        window.localStorage.setItem(STORAGE_KEY, migrated)
        window.localStorage.removeItem(STORAGE_KEY_LEGACY)
      } catch {
        /* ignore */
      }
      return migrated
    }
  } catch {
    /* storage 被禁用 (隐私模式) 时静默回退 */
  }
  return DEFAULT_THEME
}

/** 把显式主题映射到 nav bar / status bar 用的纯色 (写死值, 不走 CSS 变量) */
const THEME_COLOR: Record<PaletteName, string> = {
  cool: palettes.cool.bg,
  cream: palettes.cream.bg,
  dark: palettes.dark.bg,
}

/**
 * 把主题应用到 DOM: html[data-theme] + meta[name=theme-color]
 *
 * data-theme 永远写显式主题 (cool/cream/dark), 不会写 'auto';
 * auto 模式在 initTheme / setTheme 时通过 resolveAutoTheme 解析后写入。
 *
 * 为什么手动同步 meta: theme-color 是浏览器顶栏/状态栏颜色, 它不读 CSS 变量,
 * 必须用 JS 写死值。
 */
export function applyTheme(theme: ThemeName): PaletteName {
  if (typeof document === 'undefined') return 'cool'
  const explicit: PaletteName = theme === 'auto' ? resolveAutoTheme() : theme
  document.documentElement.setAttribute('data-theme', explicit)
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) {
    meta.setAttribute('content', THEME_COLOR[explicit])
  }
  return explicit
}

export const useThemeStore = create<State>((set) => ({
  theme: DEFAULT_THEME,
  applied: 'cool',
  setTheme: (value) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, value)
    } catch {
      /* 同上 */
    }
    const applied = applyTheme(value)
    set({ theme: value, applied })
  },
}))

/**
 * 在 main.tsx 启动时调用一次, 避免首屏闪一下。
 * 返回 unsubscribe 句柄, 组件可在 useEffect 里调。
 */
export function initTheme(): () => void {
  const value = readPersisted()
  const applied = applyTheme(value)
  useThemeStore.setState({ theme: value, applied })

  // auto 模式下监听系统主题变化, 实时切到对应显式主题
  if (typeof window === 'undefined' || !window.matchMedia) return () => undefined
  const mql = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    const current = useThemeStore.getState().theme
    if (current === 'auto') {
      const next = applyTheme('auto')
      useThemeStore.setState({ applied: next })
    }
  }
  if (mql.addEventListener) mql.addEventListener('change', onChange)
  else if (mql.addListener) mql.addListener(onChange) // 旧 Safari 兼容
  return () => {
    if (mql.removeEventListener) mql.removeEventListener('change', onChange)
    else if (mql.removeListener) mql.removeListener(onChange)
  }
}
