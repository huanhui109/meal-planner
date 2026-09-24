import { useEffect, useState } from 'react'
import { fetchMe } from '@/api/auth'
import type { CurrentUser } from '@/types'
import { LoginGate } from '@/components/LoginGate'
import { DecideScreen } from '@/components/DecideScreen'

// 入口只做一件事: 拿到 user 才进决策屏。
// 先试探 /api/auth/me (cookie 还在就直接进), 否则弹登录门。
export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => {})
      .finally(() => setChecking(false))
  }, [])

  if (checking) return null

  if (!user) {
    return (
      <div className="app">
        <LoginGate onOk={setUser} />
      </div>
    )
  }

  return <DecideScreen user={user} onAuthFail={() => setUser(null)} />
}
