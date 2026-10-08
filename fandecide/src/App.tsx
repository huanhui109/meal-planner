import { useEffect, useState } from 'react'
import { fetchMe } from '@/api/auth'
import type { CurrentUser } from '@/types'
import { LoginGate } from '@/components/LoginGate'
import { DecideScreen } from '@/components/DecideScreen'
import { WeekMenu } from '@/components/WeekMenu'
import { Shopping } from '@/components/Shopping'
import { Fridge } from '@/components/Fridge'
import { ProfileDrawer } from '@/components/ProfileDrawer'
import { TodayIcon, WeekIcon, ShoppingIcon, FridgeIcon, ProfileIcon } from '@/components/Icon'

type Tab = 'today' | 'week' | 'shopping' | 'fridge'
type Theme = 'auto' | 'light' | 'dark'

const NAVS: { key: Tab; label: string; Icon: (p: { size?: number; className?: string }) => JSX.Element }[] = [
  { key: 'today', label: '今日', Icon: TodayIcon },
  { key: 'week', label: '周菜单', Icon: WeekIcon },
  { key: 'shopping', label: '采购', Icon: ShoppingIcon },
  { key: 'fridge', label: '冰箱', Icon: FridgeIcon },
]

const PAGE_TITLE: Record<Tab, string> = {
  today: '今日',
  week: '本周菜单',
  shopping: '采购清单',
  fridge: '冰箱',
}

const PAGE_SUBTITLE: Record<Tab, string> = {
  today: '今天吃啥，我来定',
  week: '7 天网格，逐餐调整',
  shopping: '缺料自动汇总',
  fridge: '食材搜索与入库',
}

function applyTheme(t: Theme) {
  const b = document.body
  b.classList.remove('theme-light', 'theme-dark')
  if (t !== 'auto') b.classList.add(`theme-${t}`)
}

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [checking, setChecking] = useState(true)
  const [tab, setTab] = useState<Tab>('today')
  const [profileOpen, setProfileOpen] = useState(false)
  const [theme, setTheme] = useState<Theme>('auto')

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => {})
      .finally(() => setChecking(false))
  }, [])

  useEffect(() => {
    const saved = (localStorage.getItem('fandecide:theme') as Theme) || 'auto'
    setTheme(saved)
    applyTheme(saved)
  }, [])

  function changeTheme(t: Theme) {
    setTheme(t)
    localStorage.setItem('fandecide:theme', t)
    applyTheme(t)
  }

  if (checking) return null

  if (!user) {
    return (
      <div className="app">
        <LoginGate onOk={setUser} />
      </div>
    )
  }

  const initial = user.name.slice(0, 1)

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="side-context">
          <strong>饭决</strong>
          <span>{PAGE_SUBTITLE[tab]}</span>
        </div>
        <nav className="nav-list" aria-label="主要菜单">
          {NAVS.map((n) => (
            <button
              key={n.key}
              className={'nav-item' + (tab === n.key ? ' active' : '')}
              onClick={() => setTab(n.key)}
            >
              <span className="icon">
                <n.Icon />
              </span>
              <span>{n.label}</span>
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <button className="profile-button" onClick={() => setProfileOpen(true)}>
            <span className="avatar">{initial}</span>
            <span className="profile-copy">
              <b>{user.name}</b>
              <small>偏好与设置</small>
            </span>
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="mobile-top">
          <span className="mobile-title">{PAGE_TITLE[tab]}</span>
          <button className="avatar-button" aria-label="打开我的设置" onClick={() => setProfileOpen(true)}>
            <span className="avatar">{initial}</span>
          </button>
        </header>
        <div className="content">
          <section className={'page' + (tab === 'today' ? ' active' : '')}>
            <DecideScreen onAuthFail={() => setUser(null)} onOpenFridge={() => setTab('fridge')} />
          </section>
          <section className={'page' + (tab === 'week' ? ' active' : '')}>
            <WeekMenu onAuthFail={() => setUser(null)} />
          </section>
          <section className={'page' + (tab === 'shopping' ? ' active' : '')}>
            <Shopping onAuthFail={() => setUser(null)} />
          </section>
          <section className={'page' + (tab === 'fridge' ? ' active' : '')}>
            <Fridge onAuthFail={() => setUser(null)} />
          </section>
        </div>
      </main>

      <nav className="bottom-nav" aria-label="主要菜单">
        {NAVS.map((n) => (
          <button
            key={n.key}
            className={'bottom-item' + (tab === n.key ? ' active' : '')}
            onClick={() => setTab(n.key)}
          >
            <span className="icon">
              <n.Icon size={19} />
            </span>
            <span>{n.label}</span>
          </button>
        ))}
        <button className="bottom-item" onClick={() => setProfileOpen(true)}>
          <span className="icon">
            <ProfileIcon size={19} />
          </span>
          <span>我的</span>
        </button>
      </nav>

      <ProfileDrawer
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
        user={user}
        theme={theme}
        onTheme={changeTheme}
      />
    </div>
  )
}
