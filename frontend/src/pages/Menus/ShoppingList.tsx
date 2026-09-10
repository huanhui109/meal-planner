import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { message } from 'antd'
import {
  Banner,
  Card,
  Chip,
  EmptyState,
  LoadingStack,
  PageHead,
  PillButton,
} from '../../components/ui'
import { getCurrentMenu, getShoppingList } from '../../api/menu'
import { getOrderSuggestion } from '../../api/today'
import {
  categoryRank,
  formatAmount as formatQty,
  formatDateRange,
  orderStatusText,
  orderSummaryText,
  weekEnd,
} from '@shared/index'
import type { OrderSuggestion, ShoppingItem, ShoppingList as ShoppingListData } from '../../types'

interface DisplayItem extends ShoppingItem {
  checked: boolean
}

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
    const grouped = new Map<string, DisplayItem[]>()
    for (const item of data?.items ?? []) {
      const list = grouped.get(item.category) ?? []
      list.push({ ...item, checked: Boolean(checked[item.ingredient_id]) })
      grouped.set(item.category, list)
    }
    return Array.from(grouped.entries()).sort(
      ([a], [b]) => categoryRank(a) - categoryRank(b) || a.localeCompare(b),
    )
  }, [data, checked])

  const toBuy = (data?.items ?? []).filter((item) => !item.have_enough)

  const amountText = (item: ShoppingItem) =>
    item.deficit == null ? '按需' : formatQty(item.deficit, item.unit || '')

  const handleCopy = async () => {
    if (toBuy.length === 0) {
      message.info('没有需要采购的食材')
      return
    }
    const text = toBuy.map((item) => `${item.category} · ${item.name} ${amountText(item)}`).join('\n')
    try {
      await navigator.clipboard.writeText(`本周采购清单\n${text}`)
      message.success('已复制到剪贴板')
    } catch {
      message.error('复制失败, 请手动选择文本')
    }
  }

  if (loading) {
    return (
      <div className="page">
        <PageHead title="采购清单" />
        <LoadingStack rows={6} />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="page">
        <PageHead title="采购清单" subtitle="先生成菜单, 这里会自动算出缺什么" />
        <Card>
          <EmptyState
            title={error || '还没有菜单'}
            description="清单 = 菜单需要的用量 - 冰箱里已有的, 生成菜单后自动得出"
            actionLabel="去生成菜单"
            onAction={() => navigate('/menus')}
          />
        </Card>
      </div>
    )
  }

  const rangeEnd = weekEnd(data.week_start_date)
  const progress = `${data.summary.total_count - data.summary.to_buy_count}/${data.summary.total_count}`

  return (
    <div className="page">
      <PageHead
        title="采购清单"
        subtitle={
          data.summary.to_buy_count > 0
            ? `${formatDateRange(data.week_start_date, rangeEnd)} · 还要买 ${data.summary.to_buy_count} 样, 备齐 ${progress} 样`
            : `这一周需要的 ${data.summary.total_count} 样食材, 冰箱里都够了`
        }
        extra={
          <PillButton
            size="sm"
            variant={data.summary.to_buy_count > 0 ? 'ink' : 'gray'}
            onClick={handleCopy}
          >
            复制清单
          </PillButton>
        }
      />

      {order && (
        <Card className="order-card">
          <div className="card-head">
            <div>
              <div className="card-title">一键补单</div>
              <div className="card-sub">{orderSummaryText(order)}</div>
            </div>
            <Chip tone={order.reaches_min_order ? 'green' : 'warn'}>
              {orderStatusText(order)}
            </Chip>
          </div>
          {order.note && <div className="card-sub">{order.note}</div>}
          <PillButton block onClick={() => window.open(order.order_link, '_blank', 'noopener')}>
            去小象超市下单
          </PillButton>
        </Card>
      )}

      {data.summary.to_buy_count === 0 && (
        <Banner
          tone="accent"
          title="冰箱已经够用, 不用额外采购"
          text="缺什么再单独补, 或者直接开始做饭"
        />
      )}

      {data.summary.unit_mismatch_count > 0 && (
        <Banner
          title={`${data.summary.unit_mismatch_count} 项单位对不上`}
          text="库存单位与菜谱单位不一致, 已按库存为 0 计算, 需要按清单购买"
        />
      )}

      {groups.map(([category, items]) => (
        <Card key={category}>
          <div className="card-head">
            <div className="card-title">{category}</div>
            <div className="card-sub">
              {items.filter((item) => !item.have_enough).length} / {items.length} 样要买
            </div>
          </div>
          <ul className="shop-list">
            {items.map((item) => (
              <li
                key={item.ingredient_id}
                className={`shop-item ${item.have_enough ? 'is-have' : ''}`}
              >
                <button
                  type="button"
                  className="shop-name"
                  style={{
                    border: 'none',
                    background: 'none',
                    padding: 0,
                    cursor: 'pointer',
                    font: 'inherit',
                  }}
                  onClick={() =>
                    setChecked((prev) => ({
                      ...prev,
                      [item.ingredient_id]: !prev[item.ingredient_id],
                    }))
                  }
                >
                  <span
                    className="state-dot"
                    style={{
                      background: item.checked ? 'var(--color-accent)' : 'var(--color-ink3)',
                      boxShadow: 'none',
                    }}
                  />
                  {item.name}
                </button>
                <span className="shop-amount">
                  {item.have_enough ? (
                    <Chip tone="green">库存充足</Chip>
                  ) : (
                    <>
                      <span className="shop-deficit">买 {amountText(item)}</span>
                      <span className="shop-stock">
                        冰箱有 {formatQty(item.in_stock_quantity, item.unit || '')}
                      </span>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ))}

      <div className="page-footnote">
        清单由菜单用量与冰箱库存自动相减得出; 合计按食材参考价估算, 实际以下单页为准。
      </div>
    </div>
  )
}

export default ShoppingList
