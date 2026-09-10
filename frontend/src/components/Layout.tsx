import React from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Avatar, Dropdown } from 'antd'
import {
  AppstoreOutlined,
  HomeOutlined,
  InboxOutlined,
  LogoutOutlined,
  SettingOutlined,
  ShoppingCartOutlined,
} from '@ant-design/icons'
import { logout } from '../api/auth'
import type { CurrentUser } from '../types'

const TAB_ITEMS = [
  { key: '/', icon: <HomeOutlined />, label: '首页' },
  { key: '/menus', icon: <AppstoreOutlined />, label: '菜单' },
  { key: '/shopping', icon: <ShoppingCartOutlined />, label: '采购' },
  { key: '/inventory', icon: <InboxOutlined />, label: '库存' },
  { key: '/preferences', icon: <SettingOutlined />, label: '设置' },
]

function activeKey(pathname: string): string {
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

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      window.location.assign('/login')
    }
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-brand">
          <span className="app-brand-mark">🍳</span>
          <div>
            <div className="app-brand-title">每周菜谱</div>
            <div className="app-brand-sub">AI 营养配餐</div>
          </div>
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
            </Link>
          ))}
        </nav>
        <div className="app-side-footer">
          <Avatar src={user.avatar_url || undefined} size={32}>
            {user.name?.[0] ?? '用'}
          </Avatar>
          <span className="app-side-user">{user.name}</span>
          <a onClick={handleLogout} className="app-side-logout" title="退出登录">
            <LogoutOutlined />
          </a>
        </div>
      </aside>

      <main className="app-main">
        <header className="app-topbar">
          <div className="app-topbar-title">
            {TAB_ITEMS.find((item) => item.key === current)?.label ?? '首页'}
          </div>
          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                { key: 'preferences', label: '偏好设置', onClick: () => navigate('/preferences') },
                { type: 'divider' },
                { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, onClick: handleLogout },
              ],
            }}
          >
            <Avatar src={user.avatar_url || undefined} size={32} className="app-topbar-avatar">
              {user.name?.[0] ?? '用'}
            </Avatar>
          </Dropdown>
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
            </button>
          )
        })}
      </nav>
    </div>
  )
}

export default MainLayout
