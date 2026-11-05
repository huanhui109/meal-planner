import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from 'antd'
import { ArrowRightOutlined, LogoutOutlined } from '@ant-design/icons'
import { logout } from '../../api/auth'
import { useThemeStore } from '../../stores/useThemeStore'
import type { CurrentUser } from '../../types'
import AssistantConnection from '../../components/AssistantConnection'
import InboundBridgeCard from '../../components/InboundBridgeCard'

export default function Settings({ user }: { user: CurrentUser }) {
  const navigate = useNavigate()
  const { theme, setTheme } = useThemeStore()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (window.location.hash === '#assistant') document.getElementById('assistant')?.scrollIntoView()
  }, [])
  return <div className="meal-page meal-settings">
    <header className="meal-page-heading"><div><div className="meal-eyebrow">{user.name}</div><h1>偏好与设置</h1></div></header>
    {error && <Alert message={error} type="error" showIcon />}
    <section className="meal-settings-section">
      <h2>家人的口味</h2>
      <Link to="/preferences" className="meal-setting-link"><span>家庭人数、口味与长期忌口</span><ArrowRightOutlined /></Link>
    </section>
    <section className="meal-settings-section">
      <div className="meal-setting-line"><h2>外观</h2>
        <select aria-label="外观主题" value={theme} onChange={(event) => setTheme(event.target.value as typeof theme)}>
          <option value="auto">跟随系统</option><option value="cool">浅色</option>
          <option value="dark">深色</option>{theme === 'cream' && <option value="cream">浅色（原设置）</option>}
        </select></div>
    </section>
    <AssistantConnection />
    <InboundBridgeCard />
    <section className="meal-settings-section">
      <h2>保留的菜单</h2><Link to="/menus" className="meal-setting-link"><span>周菜单</span><ArrowRightOutlined /></Link>
      <Link to="/shopping" className="meal-setting-link"><span>旧菜单采购清单</span><ArrowRightOutlined /></Link>
    </section>
    <button type="button" className="meal-button" disabled={busy} onClick={() => {
      setBusy(true)
      void logout().then(() => navigate('/login', { replace: true })).catch((err: Error) => {
        setError(err.message); setBusy(false)
      })
    }}><LogoutOutlined />退出登录</button>
  </div>
}
