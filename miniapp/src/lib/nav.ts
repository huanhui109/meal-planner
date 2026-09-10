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

/** 同步自定义 TabBar 的选中态 (自定义 tabBar 不会自己高亮) */
export function syncTabBar(index: number): void {
  const pages = Taro.getCurrentPages()
  const page = pages[pages.length - 1] as unknown as { getTabBar?: () => { setSelected: (i: number) => void } }
  page?.getTabBar?.()?.setSelected(index)
}

export function toast(title: string, icon: 'success' | 'error' | 'none' = 'none'): void {
  Taro.showToast({ title, icon, duration: 2000 })
}
