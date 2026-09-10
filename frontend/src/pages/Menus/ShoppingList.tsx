import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Checkbox, Empty, Skeleton, Space, Tag, message } from 'antd'
import { CopyOutlined, ReloadOutlined } from '@ant-design/icons'
import PageHeader from '../../components/PageHeader'
import { getCurrentMenu, getShoppingList } from '../../api/menu'
import type { ShoppingItem, ShoppingList as ShoppingListData } from '../../types'

interface DisplayItem extends ShoppingItem {
  checked: boolean
}

const ShoppingList: React.FC = () => {
  const navigate = useNavigate()
  const [data, setData] = useState<ShoppingListData | null>(null)
  const [checked, setChecked] = useState<Record<number, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const menu = await getCurrentMenu()
      const result = await getShoppingList(menu.id)
      setData(result)
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
    return Array.from(grouped.entries())
  }, [data, checked])

  const toBuy = (data?.items ?? []).filter((item) => !item.have_enough)

  const formatAmount = (item: ShoppingItem) => {
    if (item.deficit == null) return '按需'
    return `${Number(item.deficit.toFixed(2))}${item.unit || ''}`
  }

  const handleCopy = async () => {
    if (toBuy.length === 0) {
      message.info('没有需要采购的食材')
      return
    }
    const text = toBuy
      .map((item) => `${item.category} · ${item.name} ${formatAmount(item)}`)
      .join('\n')
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
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="page">
        <PageHeader title="采购清单" />
        <div className="card">
          <Empty description={error || '还没有菜单, 先生成菜单吧'}>
            <Button type="primary" onClick={() => navigate('/menus')}>
              去生成菜单
            </Button>
          </Empty>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <PageHeader
        title="采购清单"
        subtitle={`${data.week_start_date} 起的一周 · 需买 ${data.summary.to_buy_count} 项 / 共 ${data.summary.total_count} 项`}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Button type="primary" icon={<CopyOutlined />} onClick={handleCopy}>
              复制清单
            </Button>
          </Space>
        }
      />

      {data.summary.unit_mismatch_count > 0 && (
        <Alert
          type="warning"
          showIcon
          className="page-alert"
          message={`${data.summary.unit_mismatch_count} 项食材的库存单位与菜谱单位不一致, 已按库存为 0 处理`}
        />
      )}
      {data.summary.to_buy_count === 0 && (
        <Alert
          type="success"
          showIcon
          className="page-alert"
          message="冰箱库存已经够用, 无需额外采购"
        />
      )}

      {groups.map(([category, items]) => (
        <div className="card" key={category}>
          <div className="card-title-row">
            <div className="card-title">{category}</div>
            <span className="card-title-sub">{items.length} 项</span>
          </div>
          <ul className="shopping-list">
            {items.map((item) => (
              <li key={item.ingredient_id} className={item.have_enough ? 'is-have' : ''}>
                <Checkbox
                  checked={item.checked}
                  onChange={(event) =>
                    setChecked((prev) => ({ ...prev, [item.ingredient_id]: event.target.checked }))
                  }
                >
                  <span className="shopping-name">{item.name}</span>
                </Checkbox>
                <span className="shopping-amount">
                  {item.have_enough ? (
                    <Tag color="green">库存充足</Tag>
                  ) : (
                    <>
                      <span className="shopping-deficit">需买 {formatAmount(item)}</span>
                      <span className="shopping-stock">
                        现有 {Number(item.in_stock_quantity.toFixed(2))}
                        {item.unit}
                      </span>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}

      <div className="page-footnote">
        清单由菜单用量与冰箱库存自动相减得出; 价格为二期接入小象超市采集后提供。
      </div>
    </div>
  )
}

export default ShoppingList
