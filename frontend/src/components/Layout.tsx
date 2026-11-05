import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { AppstoreOutlined, HistoryOutlined, CoffeeOutlined, UserOutlined } from '@ant-design/icons'
import type { CurrentUser } from '../types'

const navigation = [
  { to: '/', label: '这一餐', icon: <CoffeeOutlined /> },
  { to: '/kitchen', label: '厨房', icon: <AppstoreOutlined /> },
  { to: '/history', label: '记录', icon: <HistoryOutlined /> },
]

export default function MainLayout({ user, children }: { user: CurrentUser; children: ReactNode }) {
  return (
    <div className="meal-app">
      <a className="meal-skip" href="#main-content">跳到主要内容</a>
      <header className="meal-app-header">
        <Link to="/" className="meal-brand" aria-label="饭决首页">
          <img src="/logo-mark.svg" width="32" height="32" alt="" />
          <strong>饭决</strong><span>FANDECIDE</span>
        </Link>
        <nav className="meal-nav" aria-label="主要导航">
          {navigation.map(({ to, label, icon }) => (
            <NavLink end={to === '/'} to={to} key={to} className={({ isActive }) => isActive ? 'active' : ''}>
              {icon}<span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <Link className="meal-avatar" to="/me" aria-label="偏好与助手设置" title="偏好与助手设置">
          {user.name?.slice(0, 1) || <UserOutlined />}
        </Link>
      </header>
      <main id="main-content" className="meal-main">{children}</main>
      <footer className="meal-app-footer"><span>饭决</span><span>好好吃饭，少点纠结。</span></footer>
    </div>
  )
}
