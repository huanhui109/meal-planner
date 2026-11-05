import { useCallback, useEffect, useState } from 'react'
import { Alert, Modal, Popconfirm, Skeleton } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { addInventoryItem, deleteInventoryItem, listInventory, updateInventoryItem } from '../../api/inventory'
import type { InventoryItem } from '../../types'
import { formatAmount } from '@shared/index'

export default function Kitchen() {
  const [items, setItems] = useState<InventoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<InventoryItem | 'new' | null>(null)
  const [name, setName] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [unit, setUnit] = useState('个')
  const [expiry, setExpiry] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const load = useCallback(async () => {
    try { setItems((await listInventory()).items); setError('') }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  const open = (item: InventoryItem | 'new') => {
    setEditing(item); setFormError('')
    setName(item === 'new' ? '' : item.ingredient_name)
    setQuantity(item === 'new' ? '1' : String(item.quantity))
    setUnit(item === 'new' ? '个' : item.unit)
    setExpiry(item === 'new' ? '' : item.expiry_date ?? '')
  }
  const save = async () => {
    if (!editing || busy) return
    if (!name.trim() || !unit.trim()) { setFormError('食材名称和单位不能为空'); return }
    setBusy(true); setFormError('')
    try {
      const value = { quantity: Number(quantity), expiry_date: expiry || null }
      if (editing === 'new') await addInventoryItem({ ...value, ingredient_name: name.trim(), unit: unit.trim() })
      else await updateInventoryItem(editing.id, value)
      setEditing(null)
      await load()
    } catch (err) { setFormError((err as Error).message) }
    finally { setBusy(false) }
  }
  const remove = async (id: number) => {
    setBusy(true)
    try { await deleteInventoryItem(id); await load() }
    catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }
  const filtered = items.filter((item) => item.ingredient_name.includes(query.trim()))
  return (
    <div className="meal-page">
      <header className="meal-page-heading">
        <div><div className="meal-eyebrow">家里有什么</div><h1>厨房</h1></div>
        <button type="button" className="meal-button meal-primary" onClick={() => open('new')}><PlusOutlined />记一笔</button>
      </header>
      <div className="meal-list-toolbar">
        <label className="meal-search"><SearchOutlined /><input aria-label="搜索食材" placeholder="搜索食材"
          value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <span className="meal-muted">{items.length} 样食材</span>
      </div>
      {error && <Alert type="error" showIcon message={error} action={<button type="button" className="meal-icon"
        aria-label="重新加载库存" onClick={() => { void load() }}><ReloadOutlined /></button>} />}
      {loading ? <Skeleton active /> : filtered.length ? (
        <section className="meal-stock-list" aria-label="家中食材">
          {filtered.map((item) => (
            <article className="meal-stock-row" key={item.id}>
              <span className={`meal-fresh ${item.days_left != null && item.days_left <= 2 ? 'soon' : ''}`} />
              <div className="meal-stock-name"><h2>{item.ingredient_name}</h2><p>
                {item.days_left == null ? '未记录保质期' : item.days_left < 0 ? '已过期，请检查' :
                  item.days_left === 0 ? '今天到期' : `${item.days_left} 天后到期`}</p></div>
              <span className="meal-stock-amount">{formatAmount(item.quantity, item.unit)}</span>
              <button type="button" className="meal-icon" title="编辑食材" aria-label={`编辑${item.ingredient_name}`}
                disabled={busy} onClick={() => open(item)}><EditOutlined /></button>
              <Popconfirm title={`移除${item.ingredient_name}？`} onConfirm={() => remove(item.id)} okText="移除" cancelText="取消">
                <button type="button" className="meal-icon" title="移除食材" disabled={busy} aria-label={`移除${item.ingredient_name}`}>
                  <DeleteOutlined /></button>
              </Popconfirm>
            </article>
          ))}
        </section>
      ) : <section className="meal-empty"><h2>{query ? '没有找到这项食材' : '厨房还没有记录'}</h2>
        <p>{query ? '换个名称再找找。' : '没关系，这一餐照样能安排。'}</p>
        {!query && <button type="button" className="meal-button" onClick={() => open('new')}><PlusOutlined />添加食材</button>}
      </section>}
      <Modal title={editing === 'new' ? '记下家里的食材' : `编辑${name}`} open={editing !== null}
        onCancel={() => { if (!busy) setEditing(null) }} footer={null} width={440}>
        <form className="meal-form" onSubmit={(event) => { event.preventDefault(); void save() }}>
          {formError && <Alert type="error" message={formError} showIcon />}
          <label className="meal-field"><span>食材名称</span><input required maxLength={50} value={name}
            disabled={editing !== 'new' || busy} onChange={(event) => setName(event.target.value)} /></label>
          <label className="meal-field"><span>数量</span><input type="number" required min="0.001" max="100000" step="any"
            value={quantity} disabled={busy} onChange={(event) => setQuantity(event.target.value)} /></label>
          <label className="meal-field"><span>单位</span><input required maxLength={10} value={unit}
            disabled={editing !== 'new' || busy} onChange={(event) => setUnit(event.target.value)} /></label>
          <label className="meal-field"><span>到期日期</span><input type="date" value={expiry}
            disabled={busy} onChange={(event) => setExpiry(event.target.value)} /></label>
          <button className="meal-button meal-primary" type="submit" disabled={busy}>
            <PlusOutlined />{busy ? '正在保存…' : '保存'}</button>
        </form>
      </Modal>
    </div>
  )
}
