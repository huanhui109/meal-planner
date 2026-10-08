/**
 * 采购清单 - UI Demo 版式
 *
 * 结构照 《饭决 UI Demo.html》:
 *   page-head (标题 + 复制清单) → shopping-layout 双栏:
 *     左: 按品类分组的卡片, 每行 .shop-row (checkmark 点一下标记已买)
 *     右: 「本次补齐」汇总卡 (待买 / 预估 / 冰箱已够 + 标记本次已买齐)
 *
 * 数据逻辑不变: 清单 = 菜单需要 - 冰箱已有 (getShoppingList), 复制走 navigator.clipboard。
 * 勾选状态仍是本地的 —— 买没买是逛超市途中的临时状态, 不写库。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { message } from 'antd'
import { LoadingStack } from '../../components/ui'
import { getCurrentMenu, getShoppingList } from '../../api/menu'
import { getOrderSuggestion } from '../../api/today'
import {
  categoryRank,
  formatAmount as formatQty,
  formatMoney,
  orderStatusText,
  orderSummaryText,
} from '@shared/index'
import type { OrderSuggestion, ShoppingItem, ShoppingList as ShoppingListData } from '../../types'

const ShoppingList: React.FC = () => {
  const navigate = useNavigate()
  const [data, setData] = useState<ShoppingListData | null>(null)
  const [checked, setChecked] = useState<Record<number, boolean>>({})
  const [order, setOrder] = useState<OrderSuggestion | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const menu = await getCurrentMenu()
      const result = await getShoppingList(menu.id)
      setData(result)
      try {
        setOrder(await getOrderSuggestion(menu.id))
      } catch {
        setOrder(null)
      }
    } catch (err) {
      setError((err as Error).message)
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const groups = useMemo(() => {
    const grouped = new Map<string, ShoppingItem[]>()
    for (const item of data?.items ?? []) {
      const list = grouped.get(item.category) ?? []
      list.push(item)
      grouped.set(item.category, list)
    }
    return Array.from(grouped.entries()).sort(
      ([a], [b]) => categoryRank(a) - categoryRank(b) || a.localeCompare(b),
    )
  }, [data])

  const toBuy = (data?.items ?? []).filter((item) => !item.have_enough)
  const leftCount = toBuy.filter((item) => !checked[item.ingredient_id]).length

  /** 预估: 只加总有参考价且能算出缺口的部分, 算不出来就如实显示 — */
  const estimated = useMemo(() => {
    let sum = 0
    let counted = 0
    for (const item of toBuy) {
      if (item.reference_price != null && item.deficit != null) {
        sum += item.reference_price * item.deficit
        counted += 1
      }
    }
    return counted > 0 ? `≈${formatMoney(sum)}` : '—'
  }, [toBuy])

  const amountText = (item: ShoppingItem) =>
    item.deficit == null ? '按需' : formatQty(item.deficit, item.unit || '')

  const handleCopy = async () => {
    const lines = toBuy
      .filter((item) => !checked[item.ingredient_id])
      .map((item) => `${item.category} · ${item.name} ${amountText(item)}`)
    if (lines.length === 0) {
      message.info('没有待买食材')
      return
    }
    try {
      await navigator.clipboard.writeText(`本周采购清单\n${lines.join('\n')}`)
      message.success('采购清单已复制')
    } catch {
      message.error('复制失败, 请手动选择文本')
    }
  }

  const handleMarkAll = () => {
    const next: Record<number, boolean> = {}
    for (const item of toBuy) next[item.ingredient_id] = true
    setChecked(next)
    message.success('本次采购已标记齐全')
  }

  if (loading) {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1>采购清单</h1>
          </div>
        </div>
        <LoadingStack rows={6} />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1>采购清单</h1>
            <p>先生成菜单, 这里会自动算出缺什么</p>
          </div>
        </div>
        <div className="card">
          <div className="empty-state">
            <p>{error || '还没有菜单'}</p>
            <p className="card-sub" style={{ marginTop: 6 }}>
              清单 = 菜单需要的用量 - 冰箱里已有的, 生成菜单后自动得出
            </p>
            <div className="decision-actions" style={{ justifyContent: 'center' }}>
              <button type="button" className="button primary" onClick={() => navigate('/menus')}>
                去生成菜单
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>采购清单</h1>
          <p>
            {leftCount > 0
              ? `这周还要买 ${leftCount} 样，按区域收拢更快`
              : '这周需要的食材已经齐了'}
          </p>
        </div>
        <div className="page-head-actions">
          <button type="button" className="button small primary" onClick={() => void handleCopy()}>
            复制清单
          </button>
        </div>
      </div>

      {order && (
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">一键补单</div>
              <div className="card-sub">{orderSummaryText(order)}</div>
            </div>
            <span className={`tag ${order.reaches_min_order ? 'good' : 'warn'}`}>
              {orderStatusText(order)}
            </span>
          </div>
          {order.note && <div className="card-sub" style={{ marginBottom: 12 }}>{order.note}</div>}
          <button
            type="button"
            className="button primary"
            style={{ width: '100%' }}
            onClick={() => window.open(order.order_link, '_blank', 'noopener')}
          >
            去小象超市下单
          </button>
        </div>
      )}

      {data.summary.to_buy_count === 0 && (
        <div className="success-line" style={{ marginTop: 0 }}>
          冰箱已经够用, 不用额外采购 —— 缺什么再单独补, 或者直接开始做饭。
        </div>
      )}

      {data.summary.unit_mismatch_count > 0 && (
        <div className="card-sub">
          {data.summary.unit_mismatch_count} 项单位对不上: 库存单位与菜谱单位不一致,
          已按库存为 0 计算, 需要按清单购买。
        </div>
      )}

      <div className="shopping-layout">
        <div className="shopping-groups">
          {groups.map(([category, items]) => {
            const pending = items.filter(
              (item) => !item.have_enough && !checked[item.ingredient_id],
            ).length
            return (
              <div className="card" key={category}>
                <div className="card-head">
                  <div className="card-title">{category}</div>
                  <span className={`tag ${pending === 0 ? 'good' : ''}`}>
                    {pending > 0 ? `${pending} 样待买` : '齐了'}
                  </span>
                </div>
                <div>
                  {items.map((item) => {
                    const done = item.have_enough || Boolean(checked[item.ingredient_id])
                    return (
                      <div key={item.ingredient_id} className={`shop-row ${done ? 'done' : ''}`}>
                        <button
                          type="button"
                          className="shop-mark"
                          aria-label={done ? '恢复待买' : '标记已买'}
                          disabled={item.have_enough}
                          onClick={() =>
                            setChecked((prev) => ({
                              ...prev,
                              [item.ingredient_id]: !prev[item.ingredient_id],
                            }))
                          }
                        >
                          ✓
                        </button>
                        <div className="shop-name">
                          <b>{item.name}</b>
                          <small>
                            {item.have_enough
                              ? `冰箱有 ${formatQty(item.in_stock_quantity, item.unit || '')}，够了`
                              : item.in_stock_quantity > 0
                                ? `冰箱有 ${formatQty(item.in_stock_quantity, item.unit || '')}，还差`
                                : '冰箱没有'}
                          </small>
                        </div>
                        <div className="shop-qty">
                          {item.have_enough ? '—' : amountText(item)}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>

        <aside className="card">
          <div className="card-title">本次补齐</div>
          <div className="card-sub">只计算菜单需要、冰箱没有的部分</div>
          <div className="summary-list">
            <div>
              <span>待买</span>
              <b>{leftCount} 样</b>
            </div>
            <div>
              <span>预估</span>
              <b>{estimated}</b>
            </div>
            <div>
              <span>冰箱已够</span>
              <b>{data.summary.have_count} 样</b>
            </div>
          </div>
          <button
            type="button"
            className="button primary"
            style={{ width: '100%' }}
            disabled={toBuy.length === 0 || leftCount === 0}
            onClick={handleMarkAll}
          >
            标记本次已买齐
          </button>
        </aside>
      </div>

      <div className="page-footnote">
        清单由菜单用量与冰箱库存自动相减得出; 合计按食材参考价估算, 实际以下单页为准。
      </div>
    </div>
  )
}

export default ShoppingList
