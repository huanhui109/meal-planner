import React, { useEffect, useState } from 'react'
import { message } from 'antd'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

const GOAL_OPTIONS = ['减脂', '增肌', '控糖', '控压', '维持']

const HealthGoalForm: React.FC = () => {
  const { summary, updateHealthGoal } = usePreferenceStore()
  const [loading, setLoading] = useState(false)

  const [form, setForm] = useState({
    goal_type: '维持',
    daily_calories: 2000,
    protein_pct: 20,
    carb_pct: 50,
    fat_pct: 30,
  })

  useEffect(() => {
    if (summary?.health_goal) {
      const h = summary.health_goal
      setForm({
        goal_type: h.goal_type || '维持',
        daily_calories: h.daily_calories || 2000,
        protein_pct: h.protein_pct || 20,
        carb_pct: h.carb_pct || 50,
        fat_pct: h.fat_pct || 30,
      })
    }
  }, [summary])

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateHealthGoal(form)
      message.success('已保存健康目标')
    } catch (e) { message.error((e as Error).message || '保存失败') }
    finally { setLoading(false) }
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '12px 16px', borderRadius: '12px',
    border: '1px solid #d7d1c9', background: '#ece7e1',
    fontSize: '15px', color: '#211d1a', outline: 'none', boxSizing: 'border-box',
  }

  const total = form.protein_pct + form.carb_pct + form.fat_pct
  const pctColor = total === 100 ? '#3ccf8e' : '#ef4444'

  return (
    <div style={{ background: '#fff', borderRadius: '18px', padding: '24px', boxShadow: '0 2px 12px rgba(0,0,0,0.04)' }}>
      <div style={{ fontSize: '17px', fontWeight: 600, color: '#211d1a', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span>💪</span> 健康目标
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>目标类型</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {GOAL_OPTIONS.map(g => (
              <span key={g} onClick={() => setForm(prev => ({ ...prev, goal_type: g }))} style={{
                padding: '8px 18px', borderRadius: '12px', fontSize: '14px', cursor: 'pointer',
                background: form.goal_type === g ? '#f7663c' : '#ece7e1',
                color: form.goal_type === g ? '#fff' : '#5c5650',
                fontWeight: form.goal_type === g ? 600 : 400,
              }}>
                {g}
              </span>
            ))}
          </div>
        </div>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>每日目标热量（千卡）</label>
          <input type="number" value={form.daily_calories} min={800} max={5000}
            onChange={e => setForm(prev => ({ ...prev, daily_calories: parseInt(e.target.value) || 2000 }))}
            style={inputStyle} />
        </div>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
            <label style={{ fontSize: '13px', color: '#5c5650' }}>营养比例</label>
            <span style={{ fontSize: '12px', color: pctColor, fontWeight: 600 }}>
              合计 {total}% {total === 100 ? '✓' : '(需等于100%)'}
            </span>
          </div>
          <div style={{ display: 'flex', height: '10px', borderRadius: '5px', overflow: 'hidden', gap: '2px' }}>
            <div style={{ flex: form.protein_pct, background: '#f7663c', borderRadius: '5px 0 0 5px', transition: 'flex 0.3s' }} />
            <div style={{ flex: form.carb_pct, background: '#f4b366', transition: 'flex 0.3s' }} />
            <div style={{ flex: form.fat_pct, background: '#3ccf8e', borderRadius: '0 5px 5px 0', transition: 'flex 0.3s' }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px' }}>
            {[
              { label: '蛋白', key: 'protein_pct', color: '#f7663c' },
              { label: '碳水', key: 'carb_pct', color: '#f4b366' },
              { label: '脂肪', key: 'fat_pct', color: '#3ccf8e' },
            ].map(item => (
              <span key={item.key} style={{ fontSize: '12px', color: item.color, fontWeight: 500 }}>
                {item.label} {form[item.key as keyof typeof form] as number}%
              </span>
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginTop: '12px' }}>
            {(['protein_pct', 'carb_pct', 'fat_pct'] as const).map(key => (
              <input key={key} type="number" value={form[key]} min={10} max={70}
                onChange={e => setForm(prev => ({ ...prev, [key]: parseInt(e.target.value) || 0 }))}
                style={{ ...inputStyle, textAlign: 'center' }} />
            ))}
          </div>
        </div>
      </div>
      <button onClick={handleSave} disabled={loading || total !== 100}
        style={{
          width: '100%', marginTop: '20px', background: (loading || total !== 100) ? '#b4aba2' : '#f7663c',
          color: '#fff', border: 'none', borderRadius: '14px', padding: '14px',
          fontSize: '16px', fontWeight: 600, cursor: (loading || total !== 100) ? 'not-allowed' : 'pointer',
        }}>
        {loading ? '保存中...' : total !== 100 ? `营养比例需等于100%（当前${total}%）` : '保存健康目标'}
      </button>
    </div>
  )
}

export default HealthGoalForm
