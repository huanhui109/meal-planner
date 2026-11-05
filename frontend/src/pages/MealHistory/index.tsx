import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Skeleton } from 'antd'
import { ArrowRightOutlined, ReloadOutlined } from '@ant-design/icons'
import { mealSlotLabels, mealStatusLabels, type MealHistoryItem, type MealStatus } from '@shared/meal'
import { getMealHistory } from '../../api/meals'

export default function MealHistory() {
  const [items, setItems] = useState<MealHistoryItem[]>([])
  const [filter, setFilter] = useState<MealStatus | 'all'>('eaten')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setLoading(true)
    try { setItems(await getMealHistory()); setError('') }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  const filtered = items.filter((item) => filter === 'all' || item.status === filter)
  return <div className="meal-page">
    <header className="meal-page-heading"><div><div className="meal-eyebrow">一餐一记</div><h1>用餐记录</h1></div>
      <Link to="/menus" className="meal-text-link">旧周菜单<ArrowRightOutlined /></Link></header>
    <div className="meal-history-tabs" role="group" aria-label="记录状态">
      {(['eaten', 'accepted', 'proposed', 'rejected', 'all'] as const).map((status) =>
        <button key={status} type="button" aria-pressed={filter === status} className={filter === status ? 'active' : ''}
          onClick={() => setFilter(status)}>{status === 'all' ? '全部建议' : mealStatusLabels[status]}</button>)}
    </div>
    {error && <Alert message={error} type="error" showIcon action={<button type="button" className="meal-icon"
      aria-label="重新加载记录" onClick={() => { void load() }}><ReloadOutlined /></button>} />}
    {loading ? <Skeleton active /> : filtered.length ? <section className="meal-history-list">
      {filtered.map((item) => <article key={item.id} className="meal-history-row">
        <div className="meal-history-date"><strong>{item.meal_date.slice(5).replace('-', '.')}</strong>
          <span>{mealSlotLabels[item.meal_slot]}</span></div>
        <div className="meal-history-copy"><span className={`meal-status ${item.status}`}>{mealStatusLabels[item.status]}</span>
          <h2>{item.title}</h2><p>{item.servings} 人 · {item.mode === 'cook' ? '自己做' : '外卖'} · {item.source === 'quick' ? '快速推荐' : 'AI 调整'}</p>
        </div>
        {item.status !== 'rejected' && <Link className="meal-icon" title="查看这一餐" aria-label={`查看${item.title}`}
          to={`/?date=${item.meal_date}&slot=${item.meal_slot}`}><ArrowRightOutlined /></Link>}
      </article>)}
    </section> : <section className="meal-empty"><h2>这里还没有{filter === 'all' ? '建议' : mealStatusLabels[filter]}</h2>
      <Link className="meal-button" to="/">安排这一餐<ArrowRightOutlined /></Link></section>}
    <p className="meal-list-footnote">最近 50 份方案</p>
  </div>
}
