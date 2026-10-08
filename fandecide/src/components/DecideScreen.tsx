import { useEffect, useState } from 'react'
import { decide, feedback, lastDecision, recentDecisions, cookDecision } from '@/api/decide'
import {
  addInventory,
  deleteInventory,
  listInventory,
} from '@/api/inventory'
import { ApiError } from '@/api/client'
import type {
  DecisionResult,
  DecideRecentItem,
  InventoryItem,
} from '@/types'
import { ClockIcon, FlameIcon, TagIcon, PlusIcon } from './Icon'
import { StepsSheet } from './StepsSheet'
import { useToast } from './Toast'

const EXCLUDE_CAP = 8
const COMMON_POOL = ['鸡蛋', '番茄', '土豆', '青椒', '豆腐', '洋葱', '胡萝卜', '五花肉', '牛奶', '黄瓜']

type Stage = 'empty' | 'result' | 'accepted' | 'cooking' | 'done'

function mealContext(): { slot: string; lead: string } {
  const h = new Date().getHours()
  if (h < 5) return { slot: '夜宵', lead: '夜里' }
  if (h < 10) return { slot: '早餐', lead: '早上' }
  if (h < 14) return { slot: '午餐', lead: '中午' }
  if (h < 17) return { slot: '加餐', lead: '下午' }
  if (h < 22) return { slot: '晚餐', lead: '今晚' }
  return { slot: '夜宵', lead: '夜里' }
}

function WeatherIcon({ cond }: { cond?: string }) {
  if (cond === 'rain') return <span>🌧</span>
  if (cond === 'snow') return <span>❄️</span>
  if (cond === 'sunny' || cond === 'hot') return <span>☀️</span>
  return null
}

export function DecideScreen({
  onAuthFail,
  onOpenFridge,
}: {
  onAuthFail: () => void
  onOpenFridge: () => void
}) {
  const [result, setResult] = useState<DecisionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [excluded, setExcluded] = useState<string[]>([])
  const [stage, setStage] = useState<Stage>('empty')
  const [utterance, setUtterance] = useState('')
  const [askOpen, setAskOpen] = useState(false)
  const [sheet, setSheet] = useState(false)
  const [recent, setRecent] = useState<DecideRecentItem[]>([])
  const [inventory, setInventory] = useState<InventoryItem[]>([])
  const { show, Toast } = useToast()
  const ctx = mealContext()

  async function loadInventory() {
    try {
      const data = await listInventory()
      setInventory(data.items)
    } catch {
      /* 冰箱拉取失败不影响决策 */
    }
  }

  useEffect(() => {
    lastDecision()
      .then((r) => {
        if (r) {
          setResult(r)
          setStage(r.dish ? 'result' : 'empty')
        }
      })
      .catch(() => {})
    recentDecisions(7).then(setRecent).catch(() => {})
    loadInventory()
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
      setStage('result')
      setSheet(false)
    } catch (e) {
      fail(e)
    } finally {
      setLoading(false)
    }
  }

  async function onPrimary() {
    if (!result) return
    if (stage === 'result') {
      try {
        await feedback(result.id, true)
      } catch {
        /* 表态失败不阻断 */
      }
      setStage('accepted')
      show('这顿就定了')
    } else if (stage === 'accepted') {
      setStage('cooking')
    } else if (stage === 'cooking') {
      setLoading(true)
      try {
        const res = await cookDecision(result.id)
        if (res.already_cooked) {
          show('这顿已经扣过库存了')
        } else if (res.no_recipe) {
          show('已记下，但这是离线菜谱没法精确扣库存')
        } else {
          const miss = res.missing.length
          show(miss ? `已扣库存，${miss} 样缺料` : '已扣减冰箱库存')
        }
        setStage('done')
        loadInventory()
      } catch (e) {
        fail(e)
      } finally {
        setLoading(false)
      }
    } else {
      // done -> 再决一顿
      setStage('empty')
      setResult(null)
      setUtterance('')
    }
  }

  function reroll() {
    roll()
  }

  function reset() {
    setStage('empty')
    setResult(null)
    setUtterance('')
  }

  async function toggleQuick(name: string) {
    const owned = inventory.find((x) => x.ingredient_name === name)
    if (owned) {
      try {
        await deleteInventory(owned.id)
        show(`${name} 已移除`)
        loadInventory()
      } catch {
        show('移除失败')
      }
    } else {
      try {
        await addInventory({ ingredient_name: name, quantity: 1, unit: '份' })
        show(`${name} 已加入冰箱`)
        loadInventory()
      } catch {
        show('加入失败')
      }
    }
  }

  async function quickFill() {
    const missing = COMMON_POOL.filter((n) => !inventory.some((x) => x.ingredient_name === n))
    if (!missing.length) {
      show('常备食材都齐了')
      return
    }
    try {
      await Promise.all(missing.map((n) => addInventory({ ingredient_name: n, quantity: 1, unit: '份' })))
      show(`已补充 ${missing.length} 样常备食材`)
      loadInventory()
    } catch {
      show('补充失败')
    }
  }

  const ownedNames = new Set(inventory.map((x) => x.ingredient_name))
  const expiringSoon = inventory.filter((x) => x.expiring_soon).length
  const primaryLabel =
    stage === 'result' ? '就这个' : stage === 'accepted' ? '开始做' : stage === 'cooking' ? '做完了' : '再决一顿'
  const weather = result ? (result.weather?.condition as string | undefined) : undefined

  return (
    <div>
      <div className="status-line">
        {ctx.slot} · 家里有 {inventory.length} 样 · {expiringSoon ? `${expiringSoon} 样临期优先吃` : '库存充足'}
      </div>

      <div className="decision card">
        <div className={'decision-main ' + (stage === 'empty' ? 'decision-empty' : '')}>
          {stage === 'empty' ? (
            <>
              <h2>{ctx.lead}，别纠结</h2>
              <p className="slogan">按一下，我替你定</p>
              <button className="decide-orb" disabled={loading} onClick={roll}>
                饭决
              </button>
              <button className="ask-toggle" onClick={() => setAskOpen((v) => !v)}>
                {utterance ? `听你的：${utterance}` : '想说点什么也行，不说直接按'}
              </button>
              {askOpen ? (
                <div className="ask-panel">
                  <div className="ask-row">
                    <input
                      value={utterance}
                      placeholder="比如：清淡点，别太辣"
                      onChange={(e) => setUtterance(e.target.value)}
                    />
                    <button
                      className="button small"
                      onClick={() => {
                        show(utterance ? `已按“${utterance}”理解` : '已清空临时要求')
                        setAskOpen(false)
                      }}
                    >
                      好了
                    </button>
                  </div>
                  <div className="quick-chips">
                    {['二十分钟搞定', '别太麻烦', '冰箱有啥用啥'].map((u) => (
                      <button
                        key={u}
                        className={'chip' + (utterance === u ? ' selected' : '')}
                        onClick={() => {
                          setUtterance(u)
                          show(`已按“${u}”理解`)
                        }}
                      >
                        {u}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {error ? <div className="missing-line">{error}</div> : null}
            </>
          ) : result ? (
            <div className="result">
              <div className="dish-kicker">
                {ctx.slot} · {utterance ? `已按「${utterance}」` : '库存优先'}
              </div>
              <h1 className="dish-name">{result.dish.name}</h1>
              <div className="dish-reason">{result.reason}</div>
              <div className="dish-facts">
                {result.dish.cook_minutes ? (
                  <span>
                    <ClockIcon size={15} /> {result.dish.cook_minutes}′
                  </span>
                ) : null}
                {result.dish.calories ? (
                  <span>
                    <FlameIcon size={15} /> {result.dish.calories}
                  </span>
                ) : null}
                {result.dish.cuisine ? (
                  <span>
                    <TagIcon size={15} /> {result.dish.cuisine}
                  </span>
                ) : null}
                {weather ? (
                  <span>
                    <WeatherIcon cond={weather} /> {String(result.weather?.temperature ?? '')}
                  </span>
                ) : null}
              </div>
              <ol className="steps">
                {result.dish.steps.map((s, i) => (
                  <li key={i}>
                    <i>{i + 1}</i>
                    <span>{s}</span>
                  </li>
                ))}
              </ol>
              {stage === 'done' ? (
                <div className="success-line">已完成，冰箱库存已自动扣减 ✅</div>
              ) : null}
              <div className="result-actions">
                <button className="button primary" disabled={loading} onClick={onPrimary}>
                  {primaryLabel}
                </button>
                {stage !== 'done' ? (
                  <button className="text-button" disabled={loading} onClick={reroll}>
                    换一个
                  </button>
                ) : null}
                <button className="text-button" onClick={() => setSheet(true)}>
                  做法
                </button>
                <button className="text-button" onClick={reset}>
                  重新开始
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <aside className="decision-aside">
          {stage === 'empty' ? (
            <div>
              <h3>这一顿怎么决定</h3>
              <div className="aside-list">
                <div className="aside-row">
                  <span>临期食材</span>
                  <b>{expiringSoon} 样</b>
                </div>
                <div className="aside-row">
                  <span>已记录偏好</span>
                  <b>已读取</b>
                </div>
                <div className="aside-row">
                  <span>最近吃过</span>
                  <b>自动避开</b>
                </div>
              </div>
              <p className="aside-note">不需要先填完整资料。没有命中库存时，也会给出一份能落地的家常菜。</p>
            </div>
          ) : result ? (
            <div>
              <span className="tag good">
                库存命中{' '}
                {Math.min(
                  100,
                  50 + result.dish.ingredients.filter((g) => ownedNames.has(g)).length * 17,
                )}
                %
              </span>
              <div className="aside-dish" style={{ marginTop: 14 }}>
                {result.dish.name}
              </div>
              <div className="ingredient-mini">
                {result.dish.ingredients.map((g, i) => {
                  const hit = ownedNames.has(g)
                  return (
                    <div key={i}>
                      <span className={hit ? 'hit' : 'miss'}>{g}</span>
                      <strong>{hit ? '冰箱有' : '需采购'}</strong>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}
          <p className="aside-note">主按钮会依次推进“定下 → 开始做 → 做完了”，做完了自动扣冰箱库存。</p>
        </aside>
      </div>

      <div className="section-label">家里有啥</div>
      <div className="card quick-card">
        <div className="quick-title">
          <span>已记 {inventory.length} 样 · 点一下可增减</span>
          <button className="text-button" onClick={onOpenFridge}>
            管理冰箱 →
          </button>
        </div>
        <div className="quick-chips">
          {COMMON_POOL.map((name) => (
            <button
              key={name}
              className={'chip ' + (ownedNames.has(name) ? 'owned' : '')}
              onClick={() => toggleQuick(name)}
            >
              {ownedNames.has(name) ? '✓ ' : <PlusIcon size={13} />} {name}
            </button>
          ))}
        </div>
        <div className="quick-title" style={{ marginTop: 14 }}>
          <span className="quick-note">演示用快速增减，刷新会从服务端重新加载</span>
          <button className="text-button" onClick={quickFill}>
            补充常备食材
          </button>
        </div>
      </div>

      {recent.length ? (
        <div className="quick-note" style={{ marginTop: 10 }}>
          最近：{recent.slice(0, 5).map((r) => r.dish_name).join(' · ')}
        </div>
      ) : null}

      {sheet && result ? (
        <StepsSheet title={result.dish.name} steps={result.dish.steps} onClose={() => setSheet(false)} />
      ) : null}
      {Toast}
    </div>
  )
}
