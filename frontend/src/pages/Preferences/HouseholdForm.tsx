import React, { useEffect, useState } from 'react'
import { message } from 'antd'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

const EQUIPMENT_OPTIONS = [
  '灶台', '蒸锅', '空气炸锅', '微波炉', '烤箱',
  '电饭煲', '压力锅', '破壁机', '电磁炉', '榨汁机',
]

const HouseholdForm: React.FC = () => {
  const { summary, updateHousehold } = usePreferenceStore()
  const [loading, setLoading] = useState(false)

  const [form, setForm] = useState({
    member_count: 1,
    meals_per_day: 2,
    kitchen_equipments: [] as string[],
    weekday_cook_minutes: 30,
    weekend_cook_minutes: 60,
  })

  useEffect(() => {
    if (summary?.household) {
      const h = summary.household
      setForm({
        member_count: h.member_count,
        meals_per_day: h.meals_per_day,
        kitchen_equipments: h.kitchen_equipments ?? [],
        weekday_cook_minutes: h.weekday_cook_minutes,
        weekend_cook_minutes: h.weekend_cook_minutes,
      })
    }
  }, [summary])

  const toggleEquipment = (eq: string) => {
    setForm(prev => ({
      ...prev,
      kitchen_equipments: prev.kitchen_equipments.includes(eq)
        ? prev.kitchen_equipments.filter(e => e !== eq)
        : [...prev.kitchen_equipments, eq],
    }))
  }

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateHousehold(form)
      message.success('已保存家庭信息')
    } catch (e) {
      message.error((e as Error).message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '12px 16px',
    borderRadius: '12px',
    border: '1px solid #d7d1c9',
    background: '#ece7e1',
    fontSize: '15px',
    color: '#211d1a',
    outline: 'none',
    boxSizing: 'border-box',
  }

  return (
    <div style={{ background: '#fff', borderRadius: '18px', padding: '24px', boxShadow: '0 2px 12px rgba(0,0,0,0.04)' }}>
      <div style={{ fontSize: '17px', fontWeight: 600, color: '#211d1a', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span>👨‍👩‍👧‍👦</span> 家庭信息
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>家庭人数</label>
          <input type="number" value={form.member_count} min={1} max={20}
            onChange={e => setForm(prev => ({ ...prev, member_count: parseInt(e.target.value) || 1 }))}
            style={inputStyle} />
        </div>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>每日餐次</label>
          <input type="number" value={form.meals_per_day} min={1} max={5}
            onChange={e => setForm(prev => ({ ...prev, meals_per_day: parseInt(e.target.value) || 2 }))}
            style={inputStyle} />
        </div>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>厨房设备</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {EQUIPMENT_OPTIONS.map(eq => (
              <span key={eq} onClick={() => toggleEquipment(eq)} style={{
                padding: '6px 14px',
                borderRadius: '20px',
                fontSize: '13px',
                cursor: 'pointer',
                border: form.kitchen_equipments.includes(eq) ? '1px solid #f7663c' : '1px solid #d7d1c9',
                background: form.kitchen_equipments.includes(eq) ? 'rgba(247,102,60,0.1)' : '#ece7e1',
                color: form.kitchen_equipments.includes(eq) ? '#f7663c' : '#5c5650',
                transition: 'all 0.2s',
              }}>
                {eq}
              </span>
            ))}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>工作日做饭(分钟)</label>
            <input type="number" value={form.weekday_cook_minutes} min={5} max={180}
              onChange={e => setForm(prev => ({ ...prev, weekday_cook_minutes: parseInt(e.target.value) || 30 }))}
              style={inputStyle} />
          </div>
          <div>
            <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>周末做饭(分钟)</label>
            <input type="number" value={form.weekend_cook_minutes} min={5} max={300}
              onChange={e => setForm(prev => ({ ...prev, weekend_cook_minutes: parseInt(e.target.value) || 60 }))}
              style={inputStyle} />
          </div>
        </div>
      </div>

      <button onClick={handleSave} disabled={loading}
        style={{
          width: '100%', marginTop: '20px',
          background: loading ? '#b4aba2' : '#f7663c',
          color: '#fff', border: 'none', borderRadius: '14px',
          padding: '14px', fontSize: '16px', fontWeight: 600,
          cursor: loading ? 'not-allowed' : 'pointer',
          boxShadow: loading ? 'none' : '0 4px 16px rgba(247,102,60,0.3)',
        }}>
        {loading ? '保存中...' : '保存家庭信息'}
      </button>
    </div>
  )
}

export default HouseholdForm
