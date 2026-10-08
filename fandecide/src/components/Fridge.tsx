import { useEffect, useMemo, useState } from 'react'
import { addInventory, bulkAddInventory, deleteInventory, listInventory } from '@/api/inventory'
import type { InventoryItem } from '@/types'
import { CloseIcon } from './Icon'
import { useToast } from './Toast'

const COMMON = ['鸡蛋', '番茄', '土豆', '青椒', '豆腐', '洋葱', '胡萝卜', '牛奶', '黄瓜', '五花肉']

function freshState(it: InventoryItem): string {
  if (it.days_left == null) return 'good'
  if (it.days_left <= 1) return 'danger'
  if (it.expiring_soon) return 'warn'
  return 'good'
}

export function Fridge({ onAuthFail }: { onAuthFail: () => void }) {
  const [items, setItems] = useState<InventoryItem[]>([])
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState({ name: '', qty: '1', unit: '个' })
  const { show, Toast } = useToast()

  async function load() {
    setLoading(true)
    try {
      const data = await listInventory()
      setItems(data.items)
    } catch {
      show('冰箱加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load().catch(() => onAuthFail())
  }, [])

  const filtered = useMemo(() => {
    const k = q.trim()
    if (!k) return items
    return items.filter((i) => i.ingredient_name.includes(k))
  }, [items, q])

  const expiring = items.filter((i) => i.expiring_soon).length

  async function confirmAdd() {
    const name = form.name.trim()
    const qty = parseFloat(form.qty)
    if (!name) {
      show('先写食材名称')
      return
    }
    if (items.some((i) => i.ingredient_name === name)) {
      show(`${name} 已经在冰箱里`)
      return
    }
    try {
      await addInventory({ ingredient_name: name, quantity: qty || 1, unit: form.unit || '份' })
      setForm({ name: '', qty: '1', unit: '个' })
      setModalOpen(false)
      show(`${name} 已加入冰箱`)
      load()
    } catch {
      show('加入失败')
    }
  }

  async function quickFill() {
    const missing = COMMON.filter((n) => !items.some((i) => i.ingredient_name === n))
    if (!missing.length) {
      show('常备食材都齐了')
      return
    }
    try {
      await bulkAddInventory(missing.map((n) => ({ ingredient_name: n, quantity: 1, unit: '份' })))
      show(`已补充 ${missing.length} 样常备食材`)
      load()
    } catch {
      show('补充失败')
    }
  }

  async function remove(id: number, name: string) {
    try {
      await deleteInventory(id)
      show(`${name} 已移除`)
      load()
    } catch {
      show('移除失败')
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>冰箱</h1>
          <p>
            {items.length} 样食材 · {expiring ? `${expiring} 样建议优先吃` : '库存充足'}
          </p>
        </div>
        <button className="button small primary" onClick={() => setModalOpen(true)}>
          手动入库
        </button>
      </div>

      <div className="inventory-tools">
        <input
          className="search"
          placeholder="搜索食材"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="button" onClick={quickFill}>
          补充常备食材
        </button>
      </div>

      <div className="card inventory-card">
        {loading && !items.length ? (
          <div className="empty-state">加载中…</div>
        ) : filtered.length ? (
          <div>
            {filtered.map((it) => (
              <div className="inv-row" key={it.id}>
                <span className={'fresh ' + freshState(it)} />
                <div className="inv-name">
                  <b>{it.ingredient_name}</b>
                  <small>
                    {it.days_left == null
                      ? '未设保质期'
                      : it.days_left <= 1
                        ? `建议 ${it.days_left} 天内吃`
                        : `还可放约 ${it.days_left} 天`}
                  </small>
                </div>
                <span className="inv-qty">
                  {it.quantity} {it.unit}
                </span>
                <button
                  className="icon-button"
                  aria-label={`移除 ${it.ingredient_name}`}
                  onClick={() => remove(it.id, it.ingredient_name)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">没有匹配的食材</div>
        )}
      </div>

      {modalOpen ? (
        <div className="modal-overlay open" onClick={() => setModalOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <h2>入库一样食材</h2>
              <button className="icon-button" onClick={() => setModalOpen(false)} aria-label="关闭">
                <CloseIcon />
              </button>
            </div>
            <div className="field">
              <label htmlFor="addName">食材名称</label>
              <input
                id="addName"
                placeholder="例如：西红柿"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div className="field">
                <label htmlFor="addQty">数量</label>
                <input
                  id="addQty"
                  value={form.qty}
                  inputMode="decimal"
                  onChange={(e) => setForm({ ...form, qty: e.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="addUnit">单位</label>
                <input
                  id="addUnit"
                  value={form.unit}
                  onChange={(e) => setForm({ ...form, unit: e.target.value })}
                />
              </div>
            </div>
            <div className="modal-actions">
              <button className="button" onClick={() => setModalOpen(false)}>
                取消
              </button>
              <button className="button primary" onClick={confirmAdd}>
                加入冰箱
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {Toast}
    </div>
  )
}
