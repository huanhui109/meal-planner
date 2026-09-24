import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Skeleton, message } from 'antd'
import MainLayout from './components/Layout'
import { fetchCurrentUser } from './api/auth'
import { setUnauthorizedHandler } from './api/client'
import Login from './pages/Login'
import Today from './pages/Today'
import WeeklyView from './pages/Menus/WeeklyView'
import ShoppingList from './pages/Menus/ShoppingList'
import Inventory from './pages/Inventory'
import Preferences from './pages/Preferences'
import MePanel from './pages/Me'
import Onboarding from './pages/Onboarding'
import {
  markGuideAutoShown,
  readUserSettings,
  shouldAutoShowGuideNow,
} from './lib/user-settings'
import type { CurrentUser } from './types'

type AuthState = 'loading' | 'authenticated' | 'anonymous'

/**
 * 登录守卫 + 页面骨架
 *
 * `bare` = 不套 MainLayout (侧边栏 / TabBar / 我的抽屉)。引导页要用它:
 * 引导的唯一任务是把 3 题问完, 给用户看到第一个结果, 任何"去别的页面"的入口
 * 都是干扰 —— 而且 TabBar 会让「进饭决」之后的首屏出现两套导航。
 */
function RequireAuth({
  children,
  bare = false,
}: {
  children: (user: CurrentUser) => React.ReactNode
  bare?: boolean
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const [state, setState] = useState<AuthState>('loading')
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [redirecting, setRedirecting] = useState(false)

  // 引导只在"还没做过"时自动进一次; 已完成的用户刷新首页不会被再拉回引导。
  // 判断一律走 shared 的纯函数, 不要在这里自己写布尔表达式。
  //
  // ⚠ 为什么放 useEffect 而不是渲染期直接 <Navigate>:
  //   1. shouldAutoShowGuideNow 是纯读, 但"本次启动已弹过"这个标记是有副作用的。
  //      开 StrictMode 时渲染会被双调用, 若判断顺手消耗名额, 第二次就返回 false,
  //      重定向反而永远不触发。现在渲染期只读, 真正跳转时才 markGuideAutoShown()。
  //   2. 这道闸门本身防的是回弹死循环: 少了它, 用户在引导里答完 3 题点「进饭决」
  //      回到 /, 这里一判"该展示引导"又把人推回 /onboarding —— 永远进不去主页
  //      (showMode=每次启动 必现; once 模式下 completed 没写成功也会)。
  useEffect(() => {
    if (state !== 'authenticated' || location.pathname !== '/') return
    if (!shouldAutoShowGuideNow(readUserSettings())) return
    markGuideAutoShown()
    setRedirecting(true)
    navigate('/onboarding', { replace: true })
  }, [state, location.pathname, navigate])

  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then((current) => {
        if (cancelled) return
        setUser(current)
        setState('authenticated')
      })
      .catch((error: Error) => {
        if (cancelled) return
        if (error.message && !error.message.includes('未登录') && !error.message.includes('失效')) {
          message.error(error.message)
        }
        setState('anonymous')
      })
    return () => {
      cancelled = true
    }
  }, [location.pathname])

  if (state === 'loading') {
    return (
      <div className="app-loading">
        <Skeleton active paragraph={{ rows: 4 }} />
      </div>
    )
  }
  if (state === 'anonymous' || !user) {
    const redirect = `${location.pathname}${location.search}`
    return <Navigate to={`/login?redirect=${encodeURIComponent(redirect)}`} replace />
  }
  // 等跳转落地这段时间先继续占位, 不要先渲染一帧主页再被换掉 (会闪)
  if (redirecting) {
    return (
      <div className="app-loading">
        <Skeleton active paragraph={{ rows: 4 }} />
      </div>
    )
  }
  if (bare) return <>{children(user)}</>
  return <MainLayout user={user}>{children(user)}</MainLayout>
}

/** /me 的直连入口: 点分组走前端路由, 不整页刷新 */
function MeRoute({ user }: { user: CurrentUser }) {
  const navigate = useNavigate()
  return <MePanel user={user} onNavigate={navigate} />
}

/**
 * 把 SPA 的 navigate 注入 api 层
 *
 * 令牌真的过期时, api 层就能走前端路由跳登录页, 而不是 window.location.assign
 * 整页刷新 —— 整页刷新会把正在轮询的生成任务一起冲掉。
 */
function UnauthorizedBridge() {
  const navigate = useNavigate()
  useEffect(() => {
    setUnauthorizedHandler((target) => navigate(target))
    return () => setUnauthorizedHandler(null)
  }, [navigate])
  return null
}

function App() {
  return (
    <BrowserRouter>
      <UnauthorizedBridge />
      <Routes>
        <Route path="/login" element={<Login />} />
        {/* /me 是「我的」面板的直连入口 (抽屉从头像打开, 这条给刷新/直达用) */}
        <Route
          path="/me"
          element={
            <RequireAuth>{(user) => <MeRoute user={user} />}</RequireAuth>
          }
        />
        <Route
          path="/"
          element={<RequireAuth>{() => <Today />}</RequireAuth>}
        />
        {/*
          引导页。之前漏了这条 Route, 而守卫又是 <Navigate to="/onboarding" />:
          命中 <Route path="*"> 的 <Navigate to="/" /> 又被弹回首页, 形成
          / ⇄ /onboarding 的无限重定向 —— 守卫里那句"该弹引导"永远是 true
          (还没答完, completed 就是 false), 循环停不下来。
          「我的 → 重新做引导」的 navigate('/onboarding?from=preferences') 也同样失效。
        */}
        <Route
          path="/onboarding"
          element={<RequireAuth bare>{() => <Onboarding />}</RequireAuth>}
        />
        <Route
          path="/menus"
          element={<RequireAuth>{() => <WeeklyView />}</RequireAuth>}
        />
        <Route
          path="/shopping"
          element={<RequireAuth>{() => <ShoppingList />}</RequireAuth>}
        />
        <Route
          path="/inventory"
          element={<RequireAuth>{() => <Inventory />}</RequireAuth>}
        />
        <Route
          path="/preferences"
          element={<RequireAuth>{() => <Preferences />}</RequireAuth>}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
