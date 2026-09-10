import type { PropsWithChildren } from 'react'

import './app.scss'

/**
 * 小程序入口
 *
 * 这里不做登录拦截 (小程序没有路由守卫): 每个页面自己调用 `ensureLogin()`,
 * 未登录就跳到 pages/login, 这样从分享链接/扫码直接进来的深链也能兜住。
 */
function App({ children }: PropsWithChildren) {
  return children
}

export default App
