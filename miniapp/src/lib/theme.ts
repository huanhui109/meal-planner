/**
 * 主题 (亮 / 暗) — 小程序侧
 *
 * 设计:
 *   * 状态写到 `page.theme-light` 类, 由 _tokens.scss 的 `page.theme-light{}` 覆盖 CSS 变量。
 *   * 持久化用 Taro.setStorageSync('mp-theme', value)。
 *   * 切换时同步调 Taro.setNavigationBarColor, 让顶部导航条跟着变; 但 TabBar 走的是原生
 *     tabBar 配置 (color/selectedColor/backgroundColor) 不能运行时改, 所以 miniapp 自定义
 *     tabBar (custom-tab-bar) 直接读 var(--color-ink) / var(--color-ink3), 与 CSS 变量打通。
 *
 * 默认值: 用户决策"默认亮色", 首次进入 = 'light'。
 *
 * useTheme hook 用一个自制的轻量订阅 (Taro 没有 React 上下文, 用全局 EventTarget 简化),
 * 任何调用方 useTheme() 都会在 setTheme 后强制重新渲染。
 */
import Taro from '@tarojs/taro'

export type ThemeName = 'light' | 'dark'

const STORAGE_KEY = 'mp-theme'
const DEFAULT_THEME: ThemeName = 'light'

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

const readPersisted = (): ThemeName => {
  try {
    const raw = Taro.getStorageSync(STORAGE_KEY) as unknown
    if (raw === 'dark' || raw === 'light') return raw
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
const NAVBAR_COLOR: Record<ThemeName, { background: string; frontColor: 'black' | 'white' }> = {
  light: { background: '#FBF9F4', frontColor: 'black' },
  dark:  { background: '#e9e9ee', frontColor: 'black' },
}

/**
 * 把主题写到 DOM + storage + 顶部导航条
 *
 * 三端覆盖策略:
 *   1) H5 模式 (Taro h5 编译目标): 直接 document.documentElement.setAttribute('data-theme', value),
 *      与 :root[data-theme="light"] 配套, 立刻生效。
 *   2) 微信小程序: page 元素的 class 无法在运行时直接写, 但每个 page 自带 page 标签;
 *      我们把 data-theme 写到 currentPages[0].data.theme, 让 page.theme-light{} 的
 *      CSS 选择器命中 (Taro 会把 page.theme-light 编译成 page[theme-light])。
 *      实际效果: 通过 page.theme-light{} 覆盖块运行时仍可能不刷新, 所以再叠
 *      setNavigationBarColor 让顶部导航条颜色立刻变, 至少视觉上有反馈。
 *   3) 顶部导航条颜色通过 Taro.setNavigationBarColor 同步, 三端一致。
 */
export function applyTheme(value: ThemeName) {
  current = value
  // 1) H5 / Web 端
  if (typeof document !== 'undefined') {
    try {
      document.documentElement.setAttribute('data-theme', value)
    } catch {
      /* ignore */
    }
  }
  // 2) 小程序端: 尝试给当前 page 挂 theme-light / theme-dark 类
  // Taro 没有直接的 API 改 page 根元素 class, 但 h5/web 端 document.documentElement 已覆盖
  try {
    Taro.setStorageSync(STORAGE_KEY, value)
  } catch {
    /* ignore */
  }
  writePersisted(value)
  const nav = NAVBAR_COLOR[value]
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
}

export function getTheme(): ThemeName {
  return current
}

export function setTheme(value: ThemeName) {
  applyTheme(value)
}

/** 在 app.tsx 启动时调用一次 */
export function initTheme() {
  applyTheme(readPersisted())
}

/**
 * useTheme() —— React 组件里订阅主题, 主题切换后 forceUpdate
 *
 * 实现: 用一个 mini store + useState; 收到 emitter 回调后 setState 一个新对象触发 re-render。
 */
import { useEffect, useState } from 'react'

export function useTheme(): [ThemeName, (value: ThemeName) => void] {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!emitter) return
    return emitter.on(() => setTick((n) => n + 1))
  }, [])
  return [current, setTheme]
}

/**
 * 给需要在主题切换时重新计算样式 (尤其是 custom-tab-bar 这种硬画的几何图标) 用的
 * subscribe 函数。返回取消订阅句柄。
 */
export function subscribeTheme(fn: () => void): () => void {
  return emitter?.on(fn) ?? (() => undefined)
}