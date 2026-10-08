/**
 * 冰箱 - UI Demo 版式
 *
 * 结构照 《饭决 UI Demo.html》:
 *   page-head (标题 + 手动入库) → inventory-tools (搜索 + 补充常备食材)
 *   → 一张大卡, 每行 .inv-row (新鲜度圆点 / 名称+提示 / 数量 / 移除 ×)
 *
 * 后端接线 (2.7.0 端点):
 *   - 搜索框 oninput (防抖 300ms) → GET /inventory?q= (searchInventory)
 *   - 补充常备食材 → POST /inventory/bulk (胡萝卜/牛奶/黄瓜)
 *   - 点数量 → 弹 Demo modal 改数量 → PUT /inventory/{id}
 *   - fresh 圆点: days_left == null → good; <=1 → danger; <=2 → warn; 否则 good
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Popconfirm, message } from 'antd'
import { LoadingStack } from '../../components/ui'
import RecognizePanel from '../../components/RecognizePanel'
import {
  addInventoryItem,
  bulkAddInventory,
  deleteInventoryItem,
  listInventory,
  searchInventory,
  updateInventoryItem,
} from '../../api/inventory'
import { formatAmount } from '@shared/index'
import type { InventoryItem, RecognitionItem } from '../../types'

const SEARCH_DEBOUNCE_MS = 300

/** 补充常备食材的固定三样 (与 Demo 一致) */
const STAPLES = [
  { ingredient_name: '胡萝卜', quantity: 1, unit: '个' },
  { ingredient_name: '牛奶', quantity: 1, unit: '盒' },
  { ingredient_name: '黄瓜', quantity: 1, unit: '根' },
]

/** days_left → Demo 的 .fresh 三档 */
function freshClass(item: InventoryItem): string {
  const days = item.days_left
  if (days == null) return 'fresh'
  if (days <= 1) return 'fresh danger'
  if (days <= 2) return 'fresh warn'
  return 'fresh'
}

function freshHint(item: InventoryItem): string {
  const days = item.days_left
  if (days == null) return '未设置保质期'
  if (days <= 2) return `建议 ${Math.max(days, 0)} 天内吃`
  return `还可放约 ${days} 天`
}

const Inventory: React.FC = () => {
  const [items, setItems] = useState<InventoryItem[]>([])
  const [expiringCount, setExpiringCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [keyword, setKeyword] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [recognizeOpen, setRecognizeOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [bulking, setBulking] = useState(false)
  /** 改数量: 点哪一行就记下它, modal 里只有一个数量框 */
  const [qtyTarget, setQtyTarget] = useState<InventoryItem | null>(null)
  const [qtyDraft, setQtyDraft] = useState('')

  const [addName, setAddName] = useState('')
  const [addQty, setAddQty] = useState('1')
  const [addUnit, setAddUnit] = useState('个')

  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const applyView = useCallback((view: { expiring_count: number; items: InventoryItem[] }) => {
    setItems(view.items)
    setExpiringCount(view.expiring_count)
  }, [])

  const load = useCallback(async () => {
    try {
      applyView(await listInventory())
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [applyView])

  useEffect(() => {
    void load()
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current)
    }
  }, [load])

  /** 搜索: 防抖后打 GET /inventory?q=; 清空关键词回到全量列表 */
  const handleSearch = (value: string) => {
    setKeyword(value)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => {
      const q = value.trim()
      if (!q) {
        void load()
        return
      }
      searchInventory(q)
        .then(applyView)
        .catch((err: Error) => message.error(err.message))
    }, SEARCH_DEBOUNCE_MS)
  }

  const handleAdd = async () => {
    const name = addName.trim()
    if (!name) {
      message.info('先写食材名称')
      return
    }
    const quantity = Number(addQty) || 1
    setSaving(true)
    try {
      await addInventoryItem({
        ingredient_name: name,
        quantity,
        unit: addUnit.trim() || '份',
      })
      message.success(`${name} 已加入冰箱`)
      setAddOpen(false)
      setAddName('')
      setAddQty('1')
      setAddUnit('个')
      await load()
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const handleBulk = async () => {
    setBulking(true)
    try {
      const result = await bulkAddInventory(STAPLES)
      message.success(`已补充 ${result.added.length} 样常备食材`)
      await load()
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setBulking(false)
    }
  }

  const openQty = (item: InventoryItem) => {
    setQtyTarget(item)
    setQtyDraft(String(item.quantity))
  }

  const handleQtySave = async () => {
    if (!qtyTarget) return
    const quantity = Number(qtyDraft)
    if (!Number.isFinite(quantity) || quantity < 0) {
      message.info('数量要是一个不小于 0 的数')
      return
    }
    setSaving(true)
    try {
      await updateInventoryItem(qtyTarget.id, { quantity })
      message.success('数量已更新')
      setQtyTarget(null)
      await load()
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (item: InventoryItem) => {
    try {
      await deleteInventoryItem(item.id)
      message.success(`已移除 ${item.ingredient_name}`)
      await load()
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const handleRecognized = async (recognized: RecognitionItem[]) => {
    let saved = 0
    for (const item of recognized) {
      if (!item.name || item.quantity == null) continue
      try {
        await addInventoryItem({
          ingredient_name: item.name,
          quantity: item.quantity,
          unit: item.unit || '个',
          expiry_date: item.expiry_days
            ? new Date(Date.now() + item.expiry_days * 86400000).toISOString().slice(0, 10)
            : null,
        })
        saved += 1
      } catch {
        // 单条失败不打断整体
      }
    }
    message.success(`已入库 ${saved} 样食材`)
    setRecognizeOpen(false)
    await load()
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setAddOpen(false)
        setQtyTarget(null)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>冰箱</h1>
          <p>
            {items.length === 0
              ? '记下家里有什么, 采购清单会自动减去这些'
              : `${items.length} 样食材 · ${expiringCount > 0 ? `${expiringCount} 样建议优先吃` : '暂无临期'}`}
          </p>
        </div>
        <div className="page-head-actions">
          <button type="button" className="button small" onClick={() => setRecognizeOpen(true)}>
            拍照
          </button>
          <button
            type="button"
            className="button small primary"
            onClick={() => setAddOpen(true)}
          >
            手动入库
          </button>
        </div>
      </div>

      <div className="inventory-tools">
        <input
          className="search"
          value={keyword}
          placeholder="搜索食材"
          aria-label="搜索食材"
          onChange={(event) => handleSearch(event.target.value)}
        />
        <button type="button" className="button" disabled={bulking} onClick={() => void handleBulk()}>
          {bulking ? '补充中…' : '补充常备食材'}
        </button>
      </div>

      {loading ? (
        <LoadingStack rows={5} />
      ) : (
        <div className="card inventory-card">
          {items.length === 0 ? (
            <div className="empty-state">
              {keyword.trim() ? `没有匹配「${keyword.trim()}」的食材` : '冰箱还是空的'}
              {!keyword.trim() && (
                <div className="card-sub" style={{ marginTop: 6 }}>
                  录入常备食材后, 采购清单会只列出真正缺的东西
                </div>
              )}
            </div>
          ) : (
            <div>
              {items.map((item) => (
                <div key={item.id} className="inv-row">
                  <span className={freshClass(item)} />
                  <div className="inv-name">
                    <b>{item.ingredient_name}</b>
                    <small>{freshHint(item)}</small>
                  </div>
                  <button
                    type="button"
                    className="inv-qty"
                    title="点一下改数量"
                    onClick={() => openQty(item)}
                  >
                    {formatAmount(item.quantity, item.unit)}
                  </button>
                  <Popconfirm
                    title="删除这项库存?"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => handleDelete(item)}
                  >
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`移除 ${item.ingredient_name}`}
                    >
                      ×
                    </button>
                  </Popconfirm>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="page-footnote">
        标记「做完了」时会按菜谱用量自动扣减这里的库存; 缺料不会阻断, 只会提醒你补。
      </div>

      <RecognizePanel
        open={recognizeOpen}
        onClose={() => setRecognizeOpen(false)}
        onConfirm={handleRecognized}
      />

      {/* 手动入库 (Demo modal) */}
      <div
        className={`modal-overlay ${addOpen ? 'open' : ''}`}
        aria-hidden={!addOpen}
        onClick={(event) => {
          if (event.target === event.currentTarget) setAddOpen(false)
        }}
      >
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="addModalTitle">
          <h2 id="addModalTitle">入库一样食材</h2>
          <div className="field">
            <label htmlFor="addName">食材名称</label>
            <input
              id="addName"
              value={addName}
              placeholder="例如：西红柿"
              onChange={(event) => setAddName(event.target.value)}
            />
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="addQty">数量</label>
              <input
                id="addQty"
                value={addQty}
                inputMode="decimal"
                onChange={(event) => setAddQty(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="addUnit">单位</label>
              <input
                id="addUnit"
                value={addUnit}
                onChange={(event) => setAddUnit(event.target.value)}
              />
            </div>
          </div>
          <div className="modal-actions">
            <button type="button" className="button" onClick={() => setAddOpen(false)}>
              取消
            </button>
            <button
              type="button"
              className="button primary"
              disabled={saving}
              onClick={() => void handleAdd()}
            >
              加入冰箱
            </button>
          </div>
        </div>
      </div>

      {/* 改数量 (Demo modal) */}
      <div
        className={`modal-overlay ${qtyTarget ? 'open' : ''}`}
        aria-hidden={!qtyTarget}
        onClick={(event) => {
          if (event.target === event.currentTarget) setQtyTarget(null)
        }}
      >
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="qtyModalTitle">
          <h2 id="qtyModalTitle">改数量 · {qtyTarget?.ingredient_name}</h2>
          <div className="field">
            <label htmlFor="qtyInput">数量 ({qtyTarget?.unit})</label>
            <input
              id="qtyInput"
              value={qtyDraft}
              inputMode="decimal"
              onChange={(event) => setQtyDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleQtySave()
              }}
            />
          </div>
          <div className="modal-actions">
            <button type="button" className="button" onClick={() => setQtyTarget(null)}>
              取消
            </button>
            <button
              type="button"
              className="button primary"
              disabled={saving}
              onClick={() => void handleQtySave()}
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Inventory
