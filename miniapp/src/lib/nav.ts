/**
 * 路由与登录守卫
 *
 * 小程序的 tab 页只能用 switchTab, 非 tab 页用 navigateTo, 混用会报错,
 * 所以这里按"目标是不是 tab 页"自动选 API。
 */
import Taro from '@tarojs/taro'

import { NEXT_STEP_ROUTES } from '@shared/next-step'

import { isLoggedIn } from './session'

/** 共享层的路径 -> 小程序页面路径 */
const PAGE_MAP: Record<string, string> = {
  '/': '/pages/today/index',
  [NEXT_STEP_ROUTES.menus]: '/pages/menu/index',
  [NEXT_STEP_ROUTES.shopping]: '/pages/shopping/index',
  [NEXT_STEP_ROUTES.inventory]: '/pages/fridge/index',
  [NEXT_STEP_ROUTES.preferences]: '/pages/profile/index',
}

/** tab 页只能用 switchTab, 这里必须和 app.config.ts 的 tabBar.list 严格一致 */
const TAB_PAGES = [
  '/pages/today/index',
  '/pages/menu/index',
  '/pages/shopping/index',
  '/pages/fridge/index',
]

export function targetPage(path: string): string {
  return PAGE_MAP[path] || path
}

export function goTo(path: string): void {
  const page = targetPage(path)
  if (TAB_PAGES.includes(page)) {
    Taro.switchTab({ url: page })
    return
  }
  Taro.navigateTo({ url: page })
}

/** 每个页面 onShow 调一次: 没登录就去登录页 */
export function ensureLogin(): boolean {
  if (isLoggedIn()) return true
  Taro.reLaunch({ url: '/pages/login/index' })
  return false
}

/**
 * 同步自定义 TabBar 的选中态 (自定义 tabBar 不会自己高亮)
 *
 * ⚠️ 关键点: 小程序的 setSelected 定义在 Taro 的 React 组件实例上, 而原生
 * `page.getTabBar()` 返回的是「微信原生组件实例」, 它上面只有 `$taroInstances`
 * 指向 React 实例, 并没有 setSelected。直接调原生实例的 setSelected 会抛
 * "s.setSelected is not a function"。所以这里必须用 Taro.getTabBar(page),
 * 它内部返回的就是 `$taroInstances`(即 React 实例), 上面的 setSelected 才可用。
 *
 * 首屏或快速切 tab 时 tabBar 可能还没挂上, 这时 Taro.getTabBar 返回 undefined,
 * 所以给它几次重试的机会。
 */
export function syncTabBar(index: number): void {
  const MAX_TRY = 10
  const GAP_MS = 30
  const attempt = (n: number): void => {
    const pages = Taro.getCurrentPages()
    const page = pages[pages.length - 1] as any
    if (!page) {
      if (n < MAX_TRY) setTimeout(() => attempt(n + 1), GAP_MS)
      return
    }
    // 收集所有可能的 setSelected 载体, 任一可用即可 (兼容不同 Taro 内部结构):
    //  1) Taro.getTabBar(page) -> $taroInstances (React 实例, 推荐路径)
    //  2) 原生 getTabBar().$taroInstances 及其 .component / .reactComponent 包装
    const candidates: any[] = []
    const viaApi = Taro.getTabBar<any>(page)
    if (viaApi) candidates.push(viaApi)
    const native = page.getTabBar?.()
    if (native?.$taroInstances) {
      candidates.push(native.$taroInstances, native.$taroInstances.component, native.$taroInstances.reactComponent)
    }
    const setter = candidates
      .map((c) => (c && typeof c.setSelected === 'function' ? c.setSelected.bind(c) : undefined))
      .find(Boolean)
    if (setter) {
      setter(index)
      return
    }
    if (n < MAX_TRY) setTimeout(() => attempt(n + 1), GAP_MS)
  }
  attempt(0)
}

export function toast(title: string, icon: 'success' | 'error' | 'none' = 'none'): void {
  Taro.showToast({ title, icon, duration: 2000 })
}
