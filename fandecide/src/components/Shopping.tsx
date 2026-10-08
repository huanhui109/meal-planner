import { useEffect, useMemo, useState } from 'react'
import { getCurrentMenu } from '@/api/menus'
import { getShoppingList } from '@/api/shopping'
import { ApiError } from '@/api/client'
import type { ShoppingData, ShoppingItem } from '@/types'
import { CheckIcon } from './Icon'
import { useToast } from './Toast'

function groupByCategory(items: ShoppingItem[]): Record<string, ShoppingItem[]> {
  const map: Record<string, ShoppingItem[]> = {}
  for (const it of items) {
    ;(map[it.category] || (map[it.category] = [])).push(it)
  }
  return map
}

function qtyText(it: ShoppingItem): string {
  if (it.have_enough) return '冰箱有'
  if (!it.quantitative) return '适量'
  if (it.deficit == null) return it.required_quantity != null ? `${it.required_quantity}${it.unit}` : '适量'
  return `${it.deficit}${it.unit}`
}

export function Shopping({ onAuthFail }: { onAuthFail: () => void }) {
  const [data, setData] = useState<ShoppingData | null>(null)
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const { show, Toast } = useToast()

  async function load() {
    setLoading(true)
    try {
      const menu = await getCurrentMenu()
      const list = await getShoppingList(menu.id)
      setData(list)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onAuthFail()
      else if (e instanceof ApiError && e.status === 404) show('还没有本周菜单，先去周菜单生成')
      else show('采购清单加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const groups = useMemo(() => (data ? groupByCategory(data.items) : {}), [data])
  const left = data ? data.items.filter((i) => !i.have_enough && !checked.has(i.ingredient_id)).length : 0
  const estimate = useMemo(() => {
    if (!data) return 0
    return Math.round(
      data.items.reduce((sum, i) => {
        if (i.have_enough || i.reference_price == null || i.deficit == null) return sum
        return sum + i.deficit * i.reference_price
      }, 0),
    )
  }, [data])

  function toggle(id: number) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function markAll() {
    if (!data) return
    setChecked(new Set(data.items.filter((i) => !i.have_enough).map((i) => i.ingredient_id)))
    show('本次采购已标记齐全')
  }

  function copyList() {
    if (!data) return
    const toBuy = data.items.filter((i) => !i.have_enough && !checked.has(i.ingredient_id))
    if (!toBuy.length) {
      show('没有待买食材')
      return
    }
    const grouped = groupByCategory(toBuy)
    const text =
      '本周采购清单\n' +
      Object.keys(grouped)
        .map((cat) => grouped[cat].map((i) => `${cat} · ${i.name} ${qtyText(i)}`).join('\n'))
        .join('\n')
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(
        () => show('采购清单已复制'),
        () => show('复制失败，请手动选择'),
      )
    } else {
      show('当前环境不支持复制')
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>采购清单</h1>
          <p>{data ? `这周还要买 ${left} 样，按区域收拢更快` : '根据周菜单与冰箱库存自动汇总缺料'}</p>
        </div>
        <button className="button small primary" onClick={copyList} disabled={!data}>
          复制清单
        </button>
      </div>

      {loading && !data ? (
        <div className="card empty-state">加载中…</div>
      ) : !data ? (
        <div className="card empty-state">还没有可生成的采购清单，先去周菜单排一周。</div>
      ) : (
        <div className="shopping-layout">
          <div className="shopping-groups">
            {Object.keys(groups).map((cat) => (
              <div className="card" key={cat}>
                <div className="card-head">
                  <div className="card-title">{cat}</div>
                  <span className="tag">
                    {groups[cat].filter((i) => !i.have_enough).length} 样待买
                  </span>
                </div>
                {groups[cat].map((it) => {
                  const done = it.have_enough || checked.has(it.ingredient_id)
                  return (
                    <div className={'shop-row' + (done ? ' done' : '')} key={it.ingredient_id}>
                      <button
                        className="shop-mark"
                        aria-label={done ? '恢复待买' : '标记已买'}
                        onClick={() => toggle(it.ingredient_id)}
                      >
                        <CheckIcon size={14} />
                      </button>
                      <div className="shop-name">
                        <b>{it.name}</b>
                        <small>{it.have_enough ? '冰箱已够，不用买' : '冰箱没有'}</small>
                      </div>
                      <div className="shop-qty">{qtyText(it)}</div>
                    </div>
                  )
                })}
              </div>
            ))}
          </div>

          <aside className="card">
            <div className="card-title">本次补齐</div>
            <div className="card-sub">只计算菜单需要、冰箱没有的部分</div>
            <div className="summary-list">
              <div>
                <span>待买</span>
                <b>{left} 样</b>
              </div>
              <div>
                <span>预估</span>
                <b>¥{estimate}</b>
              </div>
              <div>
                <span>能覆盖</span>
                <b>{data.items.length} 种食材</b>
              </div>
            </div>
            <button className="button primary" style={{ width: '100%' }} onClick={markAll}>
              标记本次已买齐
            </button>
          </aside>
        </div>
      )}
      {Toast}
    </div>
  )
}
