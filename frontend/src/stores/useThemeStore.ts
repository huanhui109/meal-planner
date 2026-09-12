/**
 * 主题 (亮 / 暗) store
 *
 * 设计: 一份全局状态 + 一份 localStorage 持久化 + 一份 html[data-theme] 写入。
 * 切换时同时刷新 `<meta name="theme-color">`, 让浏览器顶栏、地址栏、手机状态栏跟上来。
 *
 * 默认值: 用户决策是 "默认亮色", 所以首次进入 = 'light'。如有需要, 把 defaultValue
 * 改成 `localStorage[k] ?? (matchMedia('(prefers-color-scheme: dark)') ? 'dark' : 'light')`
 * 即可改成"老用户沿用历史"。
 */
import { create } from 'zustand'
import type { PaletteName } from '@shared/index'

const STORAGE_KEY = 'meal-planner:theme'
const DEFAULT_THEME: PaletteName = 'light'

type State = {
  theme: PaletteName
  setTheme: (value: PaletteName) => void
}

const readPersisted = (): PaletteName => {
  if (typeof window === 'undefined') return DEFAULT_THEME
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw === 'dark' || raw === 'light') return raw
  } catch {
    /* storage 被禁用 (隐私模式) 时静默回退 */
  }
  return DEFAULT_THEME
}

/**
 * 把主题应用到 DOM: html[data-theme] + meta[name=theme-color]
 *
 * 为什么手动同步 meta: theme-color 是浏览器顶栏/状态栏颜色, 它不读 CSS 变量,
 * 必须用 JS 写死值。这里偷懒直接用 palettes 的 bg / screen 取色, 不引入额外映射。
 */
export function applyTheme(theme: PaletteName) {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute('data-theme', theme)
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) {
    meta.setAttribute(
      'content',
      theme === 'light' ? '#FBF9F4' : '#e9e9ee',
    )
  }
}

export const useThemeStore = create<State>((set) => ({
  theme: DEFAULT_THEME,
  setTheme: (value) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, value)
    } catch {
      /* 同上 */
    }
    applyTheme(value)
    set({ theme: value })
  },
}))

/** 在 main.tsx 启动时调用一次, 避免首屏闪一下 (默认 light 与用户偏好之间漂移) */
export function initTheme() {
  const value = readPersisted()
  applyTheme(value)
  useThemeStore.setState({ theme: value })
}