import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Skeleton, message } from 'antd'
import MainLayout from './components/Layout'
import { fetchCurrentUser } from './api/auth'
import Login from './pages/Login'
import Today from './pages/Today'
import WeeklyView from './pages/Menus/WeeklyView'
import ShoppingList from './pages/Menus/ShoppingList'
import Inventory from './pages/Inventory'
import Preferences from './pages/Preferences'
import MePanel from './pages/Me'
import type { CurrentUser } from './types'

type AuthState = 'loading' | 'authenticated' | 'anonymous'

function RequireAuth({ children }: { children: (user: CurrentUser) => React.ReactNode }) {
  const location = useLocation()
  const [state, setState] = useState<AuthState>('loading')
  const [user, setUser] = useState<CurrentUser | null>(null)

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
  return <MainLayout user={user}>{children(user)}</MainLayout>
}

/** /me 的直连入口: 点分组走前端路由, 不整页刷新 */
function MeRoute({ user }: { user: CurrentUser }) {
  const navigate = useNavigate()
  return <MePanel user={user} onNavigate={navigate} />
}

function App() {
  return (
    <BrowserRouter>
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
          element={<RequireAuth>{(user) => <Today user={user} />}</RequireAuth>}
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
