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
 * 启动期调用 `initTheme()` —— **模块顶层同步调用**, 不能放 useEffect:
 *   1. 读 storage `mp-theme:v2`, 旧 key `mp-theme` 自动迁移
 *   2. 探测系统深色态 (getSystemInfoSync().theme), 供 auto 解析
 *   3. 写出 applied 调色板, 页面根节点用 useThemeClass() 挂 `theme-root theme-<x>`
 *   4. auto 模式挂 Taro.onThemeChange (小程序) / matchMedia (H5) 实时跟随
 *   ⚠ 放 useEffect 的话, 页面首帧已经渲染完了才写主题, 深色用户会闪一帧浅色
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
// 模块顶层同步初始化: 首帧就要拿到正确的主题, 否则深色用户先闪一帧浅色
initTheme()

function App({ children }: PropsWithChildren) {
  useEffect(() => {
    void checkBuildOnLaunch()
  }, [])
  useEffect(() => {
    initEvents()
  }, [])
  return children
}

export default App
