/**
 * 主题 — 小程序侧 (V2.5: 冷色 / 明亮 / 深色 + auto 跟随)
 *
 * 设计:
 *   * 主题类挂在 **.theme-root** 上 (不是 page): 小程序的 page 是框架生成的根节点,
 *     运行时既拿不到引用也写不了 class, `page.theme-dark{}` 这类选择器永远命不中 ——
 *     这正是"切了主题但颜色不变"的根因。每个页面的根 <View> 用 useThemeClass()
 *     挂 `theme-root theme-<cool|cream|dark>`, 变量由 _tokens.scss 提供。
 *   * 持久化用 Taro.setStorageSync('mp-theme:v2', value), 旧 key 'mp-theme' 自动迁移。
 *   * 切换时同步调 Taro.setNavigationBarColor, 让顶部导航条跟着变; TabBar 走自定义
 *     (custom-tab-bar), 直接读 palettes[applied] 的颜色而不是硬编码。
 *
 * 默认值: V2.5 起默认 'cream' (明亮), 与 H5 一致。
 *
 * auto 模式 (真跟随):
 *   * 持久化 'auto' 字符串, 实际生效的是 'cool' 或 'dark'
 *   * 微信小程序读 Taro.getSystemInfoSync().theme, 并用 Taro.onThemeChange 实时跟随
 *   * H5 构建下走 window.matchMedia('(prefers-color-scheme: dark)')
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
let applied: PaletteName = 'cream'
/** auto 解析用的系统主题。小程序没有 window.matchMedia, 只能从 getSystemInfoSync 拿 */
let systemTheme: 'light' | 'dark' = 'light'

/**
 * 探测系统深色模式
 * 小程序: getWindowInfo().theme (基础库 2.20.1+; getSystemInfoSync 已废弃) —— 老版本回退
 *   getSystemInfoSync; 拿不到就当浅色, 不会崩
 * H5: 走 matchMedia, 由 resolveAutoTheme 内部处理
 */
function detectSystemTheme(): 'light' | 'dark' {
  try {
    const info = Taro.getWindowInfo
      ? Taro.getWindowInfo()
      : Taro.getSystemInfoSync()
    const t = (info as { theme?: string })?.theme
    return t === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

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

/** 顶部导航条颜色映射: 与 tokens.palettes 的 navBar 色对应
 *  ⚠ frontColor 微信只接受 '#000000' / '#ffffff' 两个十六进制值, 写 'black'/'white'
 *    字面量会被 setNavigationBarColor 拒绝 (invalid frontColor), 在 dev 工具里抛
 *    MiniProgramError 并触发错误边界级联 (setTimeout is not a function)。 */
const NAVBAR_COLOR: Record<PaletteName, { background: string; frontColor: '#000000' | '#ffffff' }> = {
  cool: { background: palettes.cool.bg, frontColor: '#000000' },
  cream: { background: palettes.cream.bg, frontColor: '#000000' },
  dark: { background: palettes.dark.bg, frontColor: '#ffffff' },
}

/**
 * 把主题写到 storage + 顶部导航条 + 窗口背景, 并通知所有订阅者重渲染
 *
 * 注意: 主题 **CSS 变量** 不是这里直接写 DOM, 而是由页面根节点的
 * `theme-root theme-<palette>` 类承载 —— useThemeClass() 会在 applyTheme 通知后
 * 重新取 getThemeClass(), 从而让 .theme-root.theme-dark{ --color-*: ... } 命中。
 *
 * 覆盖策略:
 *   1) H5 模式 (Taro h5 编译目标): 额外 document.documentElement.setAttribute('data-theme'),
 *      与 :root[data-theme="cream"] / [data-theme="dark"] 配套, 立刻生效。
 *   2) 微信小程序: 靠 .theme-root 包裹类 + useThemeClass() (见上)。
 *   3) 顶部导航条颜色通过 Taro.setNavigationBarColor 同步, 三端一致。
 *   4) 窗口背景 (下拉刷新露出的那块) 通过 Taro.setBackgroundColor 同步 —— app.json /
 *      page.json 里的 backgroundColor 是编译期写死值, 只能运行期覆盖 (audit B3)。
 */
export function applyTheme(value: ThemeName): PaletteName {
  current = value
  const explicit: PaletteName = value === 'auto' ? resolveAutoTheme(systemTheme) : value
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
  // 4) 窗口背景 (下拉刷新露出的那块)
  //    app.json / page.json 的 backgroundColor 是编译期写死的, 只能在这里运行期覆盖;
  //    否则深色主题下拉会闪出 config 里的冷灰 / 白色 (audit B3)。
  try {
    const bg = palettes[explicit].bg
    Taro.setBackgroundColor({
      backgroundColor: bg,
      backgroundColorTop: bg,
      backgroundColorBottom: bg,
    })
    // 下拉 loading 图的样式: 深底下要反色成浅色, 否则看不见
    Taro.setBackgroundTextStyle({ textStyle: explicit === 'dark' ? 'light' : 'dark' })
  } catch {
    /* 部分基础库 / H5 端不支持, 忽略 */
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

/**
 * 页面根节点要挂的类名: `theme-root theme-<cool|cream|dark>`
 *
 * 变量宿主在 .theme-root 上 (见 _tokens.scss), theme-<x> 决定用哪套调色板。
 * 不带 theme-root 的话, 页面会用 page 上的默认调色板 (cream), 切主题不变色。
 */
export function getThemeClass(): string {
  return `theme-root theme-${applied}`
}

export function setTheme(value: ThemeName) {
  applyTheme(value)
}

/**
 * 在 app.tsx **模块顶层同步**调用一次; 返回 unsubscribe
 *
 * 必须同步调用 (不能在 useEffect 里): 页面首帧渲染时就要拿到正确的 applied,
 * 否则深色用户会先闪一帧浅色再跳变。
 */
export function initTheme(): () => void {
  // 先探测系统主题, 再 applyTheme —— 否则 auto 模式会拿默认 light 解析
  systemTheme = detectSystemTheme()
  const value = readPersisted()
  applyTheme(value)

  const cleanups: Array<() => void> = []

  // 1) 微信小程序: 系统主题变化的实时回调 (基础库 2.15.0+, 老版本静默跳过)
  const onWxThemeChange = (Taro as unknown as {
    onThemeChange?: (cb: (res: { theme: 'light' | 'dark' }) => void) => void
  }).onThemeChange
  if (typeof onWxThemeChange === 'function') {
    try {
      onWxThemeChange((res) => {
        systemTheme = res?.theme === 'dark' ? 'dark' : 'light'
        if (current === 'auto') applyTheme('auto')
      })
    } catch {
      /* 老基础库不支持, 忽略 */
    }
  }

  // 2) H5 构建: 监听 prefers-color-scheme
  if (typeof window !== 'undefined' && window.matchMedia) {
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      systemTheme = mql.matches ? 'dark' : 'light'
      if (current === 'auto') applyTheme('auto')
    }
    if (mql.addEventListener) mql.addEventListener('change', onChange)
    else if (mql.addListener) mql.addListener(onChange)
    cleanups.push(() => {
      if (mql.removeEventListener) mql.removeEventListener('change', onChange)
      else if (mql.removeListener) mql.removeListener(onChange)
    })
  }

  return () => {
    for (const fn of cleanups) fn()
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
 * useThemeClass() —— 页面根节点挂主题类用
 *
 * 每个页面的根 <View> 都要:
 *   const themeClass = useThemeClass()
 *   <View className={cx('page', themeClass)}>
 *
 * 少了这一步, 页面就只会用 page 上的默认调色板, 切主题完全不变色 (本次修的就是这个)。
 */
export function useThemeClass(): string {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!emitter) return
    const unsubscribe = emitter.on(() => setTick((n) => n + 1))
    return () => {
      unsubscribe()
    }
  }, [])
  return getThemeClass()
}

/**
 * 给需要在主题切换时重新计算样式 (尤其是 custom-tab-bar 这种硬画的几何图标) 用的
 * subscribe 函数。返回取消订阅句柄。
 */
export function subscribeTheme(fn: () => void): () => void {
  return emitter?.on(fn) ?? (() => undefined)
}
