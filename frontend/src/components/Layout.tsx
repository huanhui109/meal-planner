import React, { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import MeSheet from './MeSheet'
import MePanel from '../pages/Me'
import { useIsGenerating } from '../stores/useGenerationStore'
import type { CurrentUser } from '../types'

/** Demo 同款线性图标 (stroke=currentColor) */
const ICONS: Record<string, React.ReactNode> = {
  today: (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  ),
  week: (
    <svg viewBox="0 0 24 24">
      <rect x="3" y="4.5" width="18" height="16" rx="3" />
      <path d="M8 2.5v4M16 2.5v4M3 9h18M7 13h3M14 13h3M7 17h3" />
    </svg>
  ),
  shopping: (
    <svg viewBox="0 0 24 24">
      <path d="M3 4h2l2.2 10.2a2 2 0 0 0 2 1.6h7.9a2 2 0 0 0 1.9-1.4L21 8H6" />
      <circle cx="10" cy="20" r="1" />
      <circle cx="18" cy="20" r="1" />
    </svg>
  ),
  fridge: (
    <svg viewBox="0 0 24 24">
      <rect x="5" y="2.5" width="14" height="19" rx="2.5" />
      <path d="M5 10h14M9 6v2M9 13v3" />
    </svg>
  ),
}

/** 4 Tab: 今日 / 周菜单 / 采购 / 冰箱 —— 「我的」从 TabBar 移出, 走头像 */
const TAB_ITEMS = [
  { key: '/', icon: ICONS.today, label: '今日' },
  { key: '/menus', icon: ICONS.week, label: '周菜单' },
  { key: '/shopping', icon: ICONS.shopping, label: '采购' },
  { key: '/inventory', icon: ICONS.fridge, label: '冰箱' },
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
  const currentLabel = TAB_ITEMS.find((item) => item.key === current)?.label ?? '今日'
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
    <div className="app demo">
      <aside className="sidebar">
        <div className="side-context">
          <strong>这一顿吃什么</strong>
          <span>饭决 · 按一下替你定</span>
        </div>
        <nav className="nav-list" aria-label="主要菜单">
          {TAB_ITEMS.map((item) => (
            <Link
              key={item.key}
              to={item.key}
              className={`nav-item ${current === item.key ? 'active' : ''}`}
            >
              <span className="icon">{item.icon}</span>
              <span>{item.label}</span>
              {generating && item.key === '/menus' && <i className="busy-dot" />}
            </Link>
          ))}
        </nav>
        <div className="side-foot">
          <button type="button" className="profile-button" onClick={openMe}>
            <span className="avatar">{user.name?.[0] ?? '用'}</span>
            <span className="profile-copy">
              <b>{user.name}</b>
              <small>偏好与设置</small>
            </span>
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="mobile-top">
          <span className="mobile-title">{currentLabel}</span>
          <button
            type="button"
            className="avatar-button"
            onClick={openMe}
            aria-label="打开我的设置"
          >
            <span className="avatar">{user.name?.[0] ?? '用'}</span>
            {generating && <i className="busy-dot busy-dot--avatar" />}
          </button>
        </header>
        <div className="content">{children}</div>
      </main>

      <nav className="bottom-nav" aria-label="主要菜单">
        {TAB_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`bottom-item ${current === item.key ? 'active' : ''}`}
            onClick={() => navigate(item.key)}
          >
            <span className="icon">{item.icon}</span>
            <span>{item.label}</span>
            {generating && item.key === '/menus' && <i className="busy-dot" />}
          </button>
        ))}
      </nav>

      <MeSheet open={meOpen} onClose={closeMe}>
        <MePanel user={user} onNavigate={goFromMe} />
      </MeSheet>
    </div>
  )
}

export default MainLayout
