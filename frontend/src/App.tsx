import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Alert, Skeleton } from 'antd'
import MainLayout from './components/Layout'
import { fetchCurrentUser } from './api/auth'
import { setUnauthorizedHandler } from './api/client'
import Login from './pages/Login'
import Meal from './pages/Meal'
import Kitchen from './pages/Kitchen'
import MealHistory from './pages/MealHistory'
import Settings from './pages/Settings'
import WeeklyView from './pages/Menus/WeeklyView'
import ShoppingList from './pages/Menus/ShoppingList'
import Preferences from './pages/Preferences/MealPreferences'
import Onboarding from './pages/Onboarding'
import type { CurrentUser } from './types'

type AuthState = 'loading' | 'authenticated' | 'anonymous' | 'error'

/** Legacy onboarding remains directly accessible but is never a prerequisite. */
function RequireAuth({
  children,
  bare = false,
}: {
  children: (user: CurrentUser) => React.ReactNode
  bare?: boolean
}) {
  const location = useLocation()
  const [state, setState] = useState<AuthState>('loading')
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [failure, setFailure] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then((current) => {
        if (cancelled) return
        setUser(current)
        setState('authenticated')
      })
      .catch((error: Error & { status?: number }) => {
        if (cancelled) return
        setFailure(error.message)
        setState(error.status === 401 ? 'anonymous' : 'error')
      })
    return () => {
      cancelled = true
    }
  }, [location.pathname, attempt])

  if (state === 'error') return <div className="app-loading"><Alert type="error" showIcon message={failure}
    action={<button type="button" className="meal-button" onClick={() => { setState('loading'); setAttempt((value) => value + 1) }}>重试连接</button>} /></div>
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
  if (bare) return <>{children(user)}</>
  return <MainLayout user={user}>{children(user)}</MainLayout>
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
        <Route
          path="/me"
          element={
            <RequireAuth>{(user) => <Settings user={user} />}</RequireAuth>
          }
        />
        <Route
          path="/"
          element={<RequireAuth>{() => <Meal />}</RequireAuth>}
        />
        <Route path="/kitchen" element={<RequireAuth>{() => <Kitchen />}</RequireAuth>} />
        <Route path="/history" element={<RequireAuth>{() => <MealHistory />}</RequireAuth>} />
        <Route
          path="/onboarding"
          element={<RequireAuth bare>{() => <Onboarding />}</RequireAuth>}
        />
        <Route
          path="/menus"
          element={<RequireAuth>{() => <div className="demo meal-legacy"><WeeklyView /></div>}</RequireAuth>}
        />
        <Route
          path="/shopping"
          element={<RequireAuth>{() => <div className="demo meal-legacy"><ShoppingList /></div>}</RequireAuth>}
        />
        <Route
          path="/inventory"
          element={<Navigate to="/kitchen" replace />}
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
