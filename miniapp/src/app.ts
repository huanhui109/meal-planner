import { useEffect, type PropsWithChildren } from 'react'

import './app.scss'
import { checkBuildOnLaunch } from './lib/build'
import { initEvents } from './lib/events'
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
 *
 * 启动期调用 `checkBuildOnLaunch()` (audit T2.4):
 *   1. 读 storage 缓存的 BuildInfo; 没有就先同步拉一次
 *   2. 比较版本, 强制升级就 reLaunch 到 /pages/update
 *   3. 普通升级就 showModal 提示 (同版本不重复)
 *
 * 启动期调用 `initEvents()` (audit T2.6):
 *   1. 读上次未上报的埋点队列 (跨启动期不丢)
 *   2. 起 30s 定时 flush
 *   3. 挂 onAppHide, 入后台时 flush 一次
 */
function App({ children }: PropsWithChildren) {
  useEffect(() => {
    return initTheme()
  }, [])
  useEffect(() => {
    void checkBuildOnLaunch()
  }, [])
  useEffect(() => {
    initEvents()
  }, [])
  return children
}

export default App
