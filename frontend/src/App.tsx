import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Skeleton, message } from 'antd'
import MainLayout from './components/Layout'
import { fetchCurrentUser } from './api/auth'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import WeeklyView from './pages/Menus/WeeklyView'
import ShoppingList from './pages/Menus/ShoppingList'
import Inventory from './pages/Inventory'
import Preferences from './pages/Preferences'
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

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={<RequireAuth>{(user) => <Dashboard user={user} />}</RequireAuth>}
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
