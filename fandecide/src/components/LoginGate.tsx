import { useState } from 'react'
import { devLogin } from '@/api/auth'
import { ApiError } from '@/api/client'
import type { CurrentUser } from '@/types'
import { SparkIcon } from './Icon'

// 本地用昵称免密登录。生产环境这里换成飞书/微信登录入口,
// 但「登录门」这一层结构不变 —— 拿不到 user 就不进主界面。
export function LoginGate({ onOk }: { onOk: (u: CurrentUser) => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit() {
    const n = name.trim()
    if (!n) return
    setBusy(true)
    setErr('')
    try {
      const u = await devLogin(n)
      onOk(u)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : '登录失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <div className="login-card card">
        <SparkIcon size={40} className="hero-mark" />
        <div className="hero-title">饭决</div>
        <div className="hero-sub">先告诉我怎么称呼你</div>
        <input
          value={name}
          placeholder="昵称"
          maxLength={12}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
        />
        <button className="button primary" disabled={busy || !name.trim()} onClick={submit}>
          {busy ? '进入中' : '进入'}
        </button>
        {err ? <div className="err">{err}</div> : null}
      </div>
    </div>
  )
}
