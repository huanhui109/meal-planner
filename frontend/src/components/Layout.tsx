import React, { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Avatar } from 'antd'
import {
  AppstoreOutlined,
  InboxOutlined,
  ShoppingCartOutlined,
  SunOutlined,
} from '@ant-design/icons'
import { LogoLockup } from './ui'
import MeSheet from './MeSheet'
import MePanel from '../pages/Me'
import { useIsGenerating } from '../stores/useGenerationStore'
import type { CurrentUser } from '../types'

/** 4 Tab: 今日 / 周菜单 / 采购 / 冰箱 —— 「我的」从 TabBar 移出, 走右上角头像 */
const TAB_ITEMS = [
  { key: '/', icon: <SunOutlined />, label: '今日' },
  { key: '/menus', icon: <AppstoreOutlined />, label: '周菜单' },
  { key: '/shopping', icon: <ShoppingCartOutlined />, label: '采购' },
  { key: '/inventory', icon: <InboxOutlined />, label: '冰箱' },
]

function activeKey(pathname: string): string {
  // 注意: 这里不能用 startsWith('/me') —— '/menus' 也满足该前缀,
  // 会把「周菜单」误判成「我的」, 导致选中态永远停在「今日」。
  if (pathname === '/me' || pathname.startsWith('/me/') || pathname.startsWith('/preferences')) {
    return '/'
  }
  const matched = TAB_ITEMS.filter((item) => item.key !== '/' && pathname.startsWith(item.key))
  return matched[0]?.key ?? '/'
}

interface LayoutProps {
  user: CurrentUser
  children: React.ReactNode
}

const MainLayout: React.FC<LayoutProps> = ({ user, children }) => {
  const navigate = useNavigate()
  const location = useLocation()
  const current = activeKey(location.pathname)
  const [meOpen, setMeOpen] = useState(false)
  // 生成要 1-2 分钟, 用户会跑去别的页面 —— 所以进度点必须全局可见
  const generating = useIsGenerating()

  const openMe = useCallback(() => {
    // 压一条历史记录, 这样手机上的返回手势/按键能直接关掉抽屉
    window.history.pushState({ me: true }, '')
    setMeOpen(true)
  }, [])

  const closeMe = useCallback(() => {
    if ((window.history.state as { me?: boolean } | null)?.me) {
      window.history.back()
      return
    }
    setMeOpen(false)
  }, [])

  // 从抽屉里跳去别的页面 (偏好设置等)。
  // 这里只能清掉占位记录再 navigate, 不能调 closeMe(): history.back() 是异步的,
  // 它会在 navigate 之后才生效, 结果把新页面又弹回原页 —— 表现就是"点了没反应"。
  const goFromMe = useCallback(
    (to: string) => {
      setMeOpen(false)
      if ((window.history.state as { me?: boolean } | null)?.me) {
        window.history.replaceState({}, '')
      }
      navigate(to)
    },
    [navigate],
  )

  useEffect(() => {
    const onPop = () => setMeOpen(false)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-brand">
          <LogoLockup />
        </div>
        <nav className="app-side-nav">
          {TAB_ITEMS.map((item) => (
            <Link
              key={item.key}
              to={item.key}
              className={`app-side-item ${current === item.key ? 'is-active' : ''}`}
            >
              {item.icon}
              <span>{item.label}</span>
              {generating && item.key === '/menus' && <i className="busy-dot" />}
            </Link>
          ))}
        </nav>
        <div className="app-side-footer">
          <button type="button" className="app-side-me" onClick={openMe}>
            <Avatar src={user.avatar_url || undefined} size={32}>
              {user.name?.[0] ?? '用'}
            </Avatar>
            <span className="app-side-user">{user.name}</span>
          </button>
        </div>
      </aside>

      <main className="app-main">
        <header className="app-topbar">
          {/* 窄屏放品牌, 宽屏放当前页名 —— 两者只显示一个 */}
          <div className="app-topbar-brand">
            <LogoLockup subtitle="" />
          </div>
          <div className="app-topbar-title">
            {TAB_ITEMS.find((item) => item.key === current)?.label ?? '今日'}
          </div>
          <button
            type="button"
            className="app-topbar-avatar"
            onClick={openMe}
            aria-label="我的"
          >
            <Avatar src={user.avatar_url || undefined} size={32}>
              {user.name?.[0] ?? '用'}
            </Avatar>
            {generating && <i className="busy-dot busy-dot--avatar" />}
          </button>
        </header>
        <div className="app-content">{children}</div>
      </main>

      <nav className="app-tabbar">
        {TAB_ITEMS.map((item) => {
          const isActive = current === item.key
          return (
            <button
              key={item.key}
              type="button"
              className={`app-tab ${isActive ? 'is-active' : ''}`}
              onClick={() => navigate(item.key)}
            >
              {item.icon}
              <span>{item.label}</span>
              {generating && item.key === '/menus' && <i className="busy-dot" />}
            </button>
          )
        })}
      </nav>

      <MeSheet open={meOpen} onClose={closeMe}>
        <MePanel user={user} onNavigate={goFromMe} />
      </MeSheet>
    </div>
  )
}

export default MainLayout
