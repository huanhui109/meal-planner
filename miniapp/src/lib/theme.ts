/**
 * 主题 — 小程序侧 (V2.5: 冷色 / 明亮 / 深色 + auto 跟随)
 *
 * 设计:
 *   * 状态写到 `page.theme-cream` / `page.theme-dark` 类 (V2.5 命名收敛: `theme-light` → `theme-cream`),
 *     由 _tokens.scss 的 `page.theme-cream{}` / `page.theme-dark{}` 覆盖 CSS 变量。
 *   * 持久化用 Taro.setStorageSync('mp-theme:v2', value), 旧 key 'mp-theme' 自动迁移。
 *   * 切换时同步调 Taro.setNavigationBarColor, 让顶部导航条跟着变; TabBar 走自定义
 *     (custom-tab-bar), 直接读 var(--color-ink) / var(--color-ink3) 跟 CSS 变量打通。
 *
 * 默认值: V2.5 起默认 'cream' (明亮), 与 H5 一致。
 *
 * auto 模式:
 *   * 持久化 'auto' 字符串
 *   * 实际写到 page class / data-theme 的是 'cool' 或 'dark'
 *   * H5 构建下, 监听 prefers-color-scheme 变化, 实时切换
 *   * 微信小程序无法监听系统, auto 退化为"启动时定格" (冷色 / 深色 由系统当前态决定)
 *
 * useTheme hook 用一个自制的轻量订阅 (Taro 没有 React 上下文, 用全局 EventTarget 简化),
 * 任何调用方 useTheme() 都会在 setTheme 后强制重新渲染。
 */
import Taro from '@tarojs/taro'
import { palettes, resolveAutoTheme, type PaletteName } from '@shared/index'

export type ThemeName = PaletteName | 'auto'

const STORAGE_KEY = 'mp-theme:v2'
const STORAGE_KEY_LEGACY = 'mp-theme'
const DEFAULT_THEME: ThemeName = 'cream'

const isValidTheme = (v: unknown): v is ThemeName =>
  v === 'cool' || v === 'cream' || v === 'dark' || v === 'auto'

/** 老值 (dark/light) 映射到新值 (cool/cream) */
const migrateLegacyValue = (raw: string): ThemeName => {
  if (raw === 'dark') return 'cool'
  if (raw === 'light') return 'cream'
  return isValidTheme(raw) ? raw : DEFAULT_THEME
}

const emitter = typeof Taro !== 'undefined' && typeof globalThis !== 'undefined'
  ? new (class {
      listeners = new Set<() => void>()
      on(fn: () => void) {
        this.listeners.add(fn)
        return () => this.listeners.delete(fn)
      }
      emit() {
        for (const fn of this.listeners) fn()
      }
    })()
  : null

let current: ThemeName = DEFAULT_THEME
let applied: PaletteName = 'cool'

const readPersisted = (): ThemeName => {
  try {
    const raw = Taro.getStorageSync(STORAGE_KEY) as unknown
    if (raw && isValidTheme(raw)) return raw
    const legacy = Taro.getStorageSync(STORAGE_KEY_LEGACY) as unknown
    if (legacy) {
      const migrated = migrateLegacyValue(String(legacy))
      try {
        Taro.setStorageSync(STORAGE_KEY, migrated)
        Taro.removeStorageSync(STORAGE_KEY_LEGACY)
      } catch {
        /* ignore */
      }
      return migrated
    }
  } catch {
    /* storage 不可用 */
  }
  return DEFAULT_THEME
}

const writePersisted = (value: ThemeName) => {
  try {
    Taro.setStorageSync(STORAGE_KEY, value)
  } catch {
    /* ignore */
  }
}

/** 顶部导航条颜色映射: 与 tokens.palettes 的 navBar 色对应 */
const NAVBAR_COLOR: Record<PaletteName, { background: string; frontColor: 'black' | 'white' }> = {
  cool: { background: palettes.cool.bg, frontColor: 'black' },
  cream: { background: palettes.cream.bg, frontColor: 'black' },
  dark: { background: palettes.dark.bg, frontColor: 'white' },
}

/**
 * 把主题写到 DOM + storage + 顶部导航条
 *
 * 三端覆盖策略:
 *   1) H5 模式 (Taro h5 编译目标): 直接 document.documentElement.setAttribute('data-theme', explicit),
 *      与 :root[data-theme="cream"] / [data-theme="dark"] 配套, 立刻生效。
 *   2) 微信小程序: page 元素的 class 无法在运行时直接写, 但每个 page 自带 page 标签;
 *      用 page.theme-cream / page.theme-dark 类 (Taro 编译时映射)。如果 page 元素 class
 *      写不了, 至少 nav bar 颜色能立即变, 给用户视觉反馈。
 *   3) 顶部导航条颜色通过 Taro.setNavigationBarColor 同步, 三端一致。
 */
export function applyTheme(value: ThemeName): PaletteName {
  current = value
  const explicit: PaletteName = value === 'auto' ? resolveAutoTheme() : value
  applied = explicit

  // 1) H5 / Web 端
  if (typeof document !== 'undefined') {
    try {
      document.documentElement.setAttribute('data-theme', explicit)
    } catch {
      /* ignore */
    }
  }
  // 2) 持久化
  try {
    Taro.setStorageSync(STORAGE_KEY, value)
  } catch {
    /* ignore */
  }
  writePersisted(value)
  // 3) 顶部导航条
  const nav = NAVBAR_COLOR[explicit]
  try {
    Taro.setNavigationBarColor({
      frontColor: nav.frontColor,
      backgroundColor: nav.background,
      animation: { duration: 200, timingFunc: 'easeIn' },
    })
  } catch {
    /* ignore */
  }
  emitter?.emit()
  return explicit
}

export function getTheme(): ThemeName {
  return current
}

export function getApplied(): PaletteName {
  return applied
}

export function setTheme(value: ThemeName) {
  applyTheme(value)
}

/** 在 app.tsx 启动时调用一次; 返回 unsubscribe, 组件可在 useEffect 里调 */
export function initTheme(): () => void {
  const value = readPersisted()
  applyTheme(value)

  // auto 模式下 (H5 构建) 监听系统主题变化
  if (typeof window === 'undefined' || !window.matchMedia) return () => undefined
  const mql = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    if (current === 'auto') applyTheme('auto')
  }
  if (mql.addEventListener) mql.addEventListener('change', onChange)
  else if (mql.addListener) mql.addListener(onChange)
  return () => {
    if (mql.removeEventListener) mql.removeEventListener('change', onChange)
    else if (mql.removeListener) mql.removeListener(onChange)
  }
}

/**
 * useTheme() —— React 组件里订阅主题, 主题切换后 forceUpdate
 *
 * 返回 [theme, setTheme, applied], 其中 applied 是 auto 模式解析后的实际主题,
 * 给 Logo 这种"按显式主题走"的组件用。
 */
import { useEffect, useState } from 'react'

export function useTheme(): [ThemeName, (value: ThemeName) => void, PaletteName] {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!emitter) return
    const unsubscribe = emitter.on(() => setTick((n) => n + 1))
    return () => {
      unsubscribe()
    }
  }, [])
  return [current, setTheme, applied]
}

/**
 * 给需要在主题切换时重新计算样式 (尤其是 custom-tab-bar 这种硬画的几何图标) 用的
 * subscribe 函数。返回取消订阅句柄。
 */
export function subscribeTheme(fn: () => void): () => void {
  return emitter?.on(fn) ?? (() => undefined)
}
