import React, { useEffect, useState } from 'react'
import { message } from 'antd'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

const AllergyForm: React.FC = () => {
  const { summary, updateAllergy } = usePreferenceStore()
  const [loading, setLoading] = useState(false)
  const [inputVal, setInputVal] = useState('')
  const [inputMode, setInputMode] = useState<'allergens' | 'avoid_ingredients'>('allergens')

  const [form, setForm] = useState({
    allergens: [] as string[],
    avoid_ingredients: [] as string[],
    dietary_restrictions: '',
  })

  useEffect(() => {
    if (summary?.allergy_restriction) {
      const a = summary.allergy_restriction
      setForm({
        allergens: a.allergens ?? [],
        avoid_ingredients: a.avoid_ingredients ?? [],
        dietary_restrictions: a.dietary_restrictions || '',
      })
    }
  }, [summary])

  const removeItem = (type: 'allergens' | 'avoid_ingredients', item: string) => {
    setForm(prev => ({ ...prev, [type]: prev[type].filter(i => i !== item) }))
  }

  const addItem = () => {
    if (!inputVal.trim()) return
    const target = inputMode
    setForm(prev => ({
      ...prev,
      [target]: [...prev[target], inputVal.trim()],
    }))
    setInputVal('')
  }

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateAllergy(form)
      message.success('已保存忌口设置')
    } catch (e) { message.error((e as Error).message || '保存失败') }
    finally { setLoading(false) }
  }

  const inputStyle: React.CSSProperties = {
    flex: 1, padding: '12px 16px', borderRadius: '12px',
    border: '1px solid #d7d1c9', background: '#ece7e1',
    fontSize: '15px', color: '#211d1a', outline: 'none',
  }

  const TagList = ({ items, color }: { items: string[], color: string }) => (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
      {items.length === 0 && <span style={{ fontSize: '13px', color: '#b4aba2' }}>暂无</span>}
      {items.map(item => (
        <span key={item} style={{
          display: 'inline-flex', alignItems: 'center', gap: '4px',
          padding: '6px 12px', borderRadius: '20px', fontSize: '13px',
          background: color === 'red' ? 'rgba(239,68,68,0.1)' : 'rgba(244,179,102,0.1)',
          color: color === 'red' ? '#ef4444' : '#f4b366',
          border: `1px solid ${color === 'red' ? '#ef4444' : '#f4b366'}`,
        }}>
          {item}
          <span onClick={() => removeItem(color === 'red' ? 'allergens' : 'avoid_ingredients', item)}
            style={{ cursor: 'pointer', marginLeft: '2px', opacity: 0.7 }}>✕</span>
        </span>
      ))}
    </div>
  )

  return (
    <div style={{ background: '#fff', borderRadius: '18px', padding: '24px', boxShadow: '0 2px 12px rgba(0,0,0,0.04)' }}>
      <div style={{ fontSize: '17px', fontWeight: 600, color: '#211d1a', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span>⚠️</span> 忌口过敏
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div>
          <label style={{ fontSize: '13px', color: '#ef4444', fontWeight: 600, marginBottom: '6px', display: 'block' }}>
            🚫 过敏源（绝对禁止）
          </label>
          <TagList items={form.allergens} color="red" />
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <input value={inputMode === 'allergens' ? inputVal : ''} placeholder="输入过敏源"
              onChange={e => { setInputMode('allergens'); setInputVal(e.target.value) }}
              style={inputStyle} />
            <button onClick={() => { if (inputMode === 'allergens') addItem() }}
              style={{ padding: '12px 20px', borderRadius: '12px', border: 'none', background: '#ef4444', color: '#fff', fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap' }}>
              添加
            </button>
          </div>
        </div>
        <div>
          <label style={{ fontSize: '13px', color: '#f4b366', fontWeight: 600, marginBottom: '6px', display: 'block' }}>
            🟡 忌口食材（尽量避免）
          </label>
          <TagList items={form.avoid_ingredients} color="yellow" />
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <input value={inputMode === 'avoid_ingredients' ? inputVal : ''} placeholder="输入忌口食材"
              onChange={e => { setInputMode('avoid_ingredients'); setInputVal(e.target.value) }}
              style={inputStyle} />
            <button onClick={() => { if (inputMode === 'avoid_ingredients') addItem() }}
              style={{ padding: '12px 20px', borderRadius: '12px', border: 'none', background: '#f4b366', color: '#fff', fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap' }}>
              添加
            </button>
          </div>
        </div>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>饮食限制说明</label>
          <input value={form.dietary_restrictions} placeholder="如清真、素食等"
            onChange={e => setForm(prev => ({ ...prev, dietary_restrictions: e.target.value }))}
            style={{ width: '100%', padding: '12px 16px', borderRadius: '12px', border: '1px solid #d7d1c9', background: '#ece7e1', fontSize: '15px', color: '#211d1a', outline: 'none', boxSizing: 'border-box' }} />
        </div>
      </div>
      <button onClick={handleSave} disabled={loading}
        style={{
          width: '100%', marginTop: '20px', background: loading ? '#b4aba2' : '#f7663c',
          color: '#fff', border: 'none', borderRadius: '14px', padding: '14px',
          fontSize: '16px', fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
        }}>
        {loading ? '保存中...' : '保存忌口设置'}
      </button>
    </div>
  )
}

export default AllergyForm
