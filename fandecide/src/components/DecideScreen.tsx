import { useEffect, useState } from 'react'
import { decide, feedback, lastDecision, recentDecisions } from '@/api/decide'
import { ApiError } from '@/api/client'
import type { CurrentUser, DecisionResult, DecideRecentItem } from '@/types'
import { ResultCard } from './ResultCard'
import { StepsSheet } from './StepsSheet'
import { SparkIcon } from './Icon'

const EXCLUDE_CAP = 8 // 本次会话记这么多拒绝过的菜, 换一个时带上去重

export function DecideScreen({
  user,
  onAuthFail,
}: {
  user: CurrentUser
  onAuthFail: () => void
}) {
  const [result, setResult] = useState<DecisionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [excluded, setExcluded] = useState<string[]>([])
  const [sheet, setSheet] = useState(false)
  const [recent, setRecent] = useState<DecideRecentItem[]>([])
  const [toast, setToast] = useState('')

  // 冷启动: 上一次决策秒开结果卡, 不必重新摇; 顺便拉一条轻历史
  useEffect(() => {
    lastDecision()
      .then(setResult)
      .catch(() => {})
    recentDecisions(7)
      .then(setRecent)
      .catch(() => {})
  }, [])

  function fail(e: unknown) {
    if (e instanceof ApiError && e.status === 401) {
      onAuthFail()
      return
    }
    setError(e instanceof ApiError ? e.message : '出了点问题，再按一次试试')
  }

  async function roll() {
    if (loading) return
    setLoading(true)
    setError('')
    try {
      const r = await decide({ exclude: excluded.slice(-EXCLUDE_CAP) })
      setResult(r)
      setExcluded((p) => [...p, r.dish.name].slice(-EXCLUDE_CAP))
      setSheet(false)
    } catch (e) {
      fail(e)
    } finally {
      setLoading(false)
    }
  }

  async function keep() {
    if (!result) return
    try {
      await feedback(result.id, true)
      setToast('记下了，去做吧')
      setTimeout(() => setToast(''), 1600)
    } catch (e) {
      fail(e)
    }
  }

  return (
    <div className="app">
      <div className="topbar">
        <span className="who">
          <span className="avatar">{user.name.slice(0, 1)}</span>
          {user.name}
        </span>
        <span>今天吃啥</span>
      </div>

      <div className="stage">
        {!result ? (
          <div className="hero">
            <SparkIcon size={44} className="hero-mark" />
            <h2 className="hero-title">饭决</h2>
            <div className="hero-sub">按一下，这顿就有了</div>
            <button className="decide-btn" disabled={loading} onClick={roll}>
              {loading ? '决定中' : '饭决'}
            </button>
            {error ? <div className="err">{error}</div> : null}
          </div>
        ) : (
          <ResultCard
            result={result}
            loading={loading}
            onRoll={roll}
            onKeep={keep}
            onSteps={() => setSheet(true)}
          />
        )}
      </div>

      {recent.length ? (
        <div className="recent">
          <div className="recent-row">
            {recent.map((r) => (
              <span className="recent-item" key={r.id}>
                <span className="dot">·</span>
                {r.dish_name}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {toast ? <div className="err">{toast}</div> : null}

      {sheet && result ? <StepsSheet dish={result.dish} onClose={() => setSheet(false)} /> : null}
    </div>
  )
}
