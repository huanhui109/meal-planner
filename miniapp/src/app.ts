import { useEffect, type PropsWithChildren } from 'react'

import './app.scss'
import { initTheme } from './lib/theme'

/**
 * 小程序入口
 *
 * 这里不做登录拦截 (小程序没有路由守卫): 每个页面自己调用 `ensureLogin()`,
 * 未登录就跳到 pages/login, 这样从分享链接/扫码直接进来的深链也能兜住。
 *
 * 启动期调用 `initTheme()`:
 *   1. 读 storage `mp-theme:v2`, 旧 key `mp-theme` 自动迁移
 *   2. 写 `data-theme` + 顶部导航条颜色同步切换
 *   3. auto 模式下挂 matchMedia 监听系统主题变化 (H5 构建生效)
 */
function App({ children }: PropsWithChildren) {
  useEffect(() => {
    return initTheme()
  }, [])
  return children
}

export default App
