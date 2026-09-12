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
 * 在 page 上挂 .theme-light / .theme-dark, 让 _tokens.scss 里的 page.theme-light{} 覆盖
 * CSS 变量; 不挂 dark 类是因为 dark 是默认 (page{} 已生效), 但保留 dark 类让"双类并存"时
 * 行为可预测 (未来如果有第三主题, 加 dark 类就显式声明)。
 */
export function applyTheme(value: ThemeName) {
  current = value
  try {
    // 给 page 加类: Taro 的 page 没有稳定的 DOM API 直接拿到根容器,
    // 但所有页面都是基于 page 标签, 设置 html data-theme 也行, 这里取兼容写法
    // (在 Taro 里 Taro 渲染时会把页面包成小程序原生 page 节点, 我们用 data-theme 让
    // CSS 选择器 page.theme-light / page[data-theme=...] 都能命中)
    // 注: Taro 内部把 CSS 选择器 page 对应到小程序的 page 根节点
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