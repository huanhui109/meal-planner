import React, { useEffect, useState } from 'react'
import { message } from 'antd'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

const BudgetForm: React.FC = () => {
  const { summary, updateBudget } = usePreferenceStore()
  const [loading, setLoading] = useState(false)

  const [form, setForm] = useState({
    weekday_daily_budget: 35,
    weekend_daily_budget: 80,
    weekly_cap: 350,
    min_meal_budget: 8,
  })

  useEffect(() => {
    if (summary?.budget) {
      const b = summary.budget
      setForm({
        weekday_daily_budget: b.weekday_daily_budget || 35,
        weekend_daily_budget: b.weekend_daily_budget || 80,
        weekly_cap: b.weekly_cap || 350,
        min_meal_budget: b.min_meal_budget || 8,
      })
    }
  }, [summary])

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateBudget(form)
      message.success('已保存预算')
    } catch (e) { message.error((e as Error).message || '保存失败') }
    finally { setLoading(false) }
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '12px 16px', borderRadius: '12px',
    border: '1px solid #d7d1c9', background: '#ece7e1',
    fontSize: '15px', color: '#211d1a', outline: 'none', boxSizing: 'border-box',
  }

  return (
    <div style={{ background: '#fff', borderRadius: '18px', padding: '24px', boxShadow: '0 2px 12px rgba(0,0,0,0.04)' }}>
      <div style={{ fontSize: '17px', fontWeight: 600, color: '#211d1a', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span>💰</span> 预算配置
      </div>

      {/* 预算信息提示 */}
      <div style={{
        background: 'rgba(244,179,102,0.1)', borderRadius: '12px',
        padding: '12px 16px', marginBottom: '16px', fontSize: '13px',
        color: '#f4b366', lineHeight: 1.5,
      }}>
        💡 预算配置将帮助 AI 在生成菜单时控制每餐成本
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>工作日每日预算（元）</label>
            <div style={{ position: 'relative' }}>
              <span style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: '#b4aba2', fontSize: '15px' }}>¥</span>
              <input type="number" value={form.weekday_daily_budget} min={5}
                onChange={e => setForm(prev => ({ ...prev, weekday_daily_budget: parseFloat(e.target.value) || 35 }))}
                style={{ ...inputStyle, paddingLeft: '32px' }} />
            </div>
          </div>
          <div>
            <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>周末每日预算（元）</label>
            <div style={{ position: 'relative' }}>
              <span style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: '#b4aba2', fontSize: '15px' }}>¥</span>
              <input type="number" value={form.weekend_daily_budget} min={5}
                onChange={e => setForm(prev => ({ ...prev, weekend_daily_budget: parseFloat(e.target.value) || 80 }))}
                style={{ ...inputStyle, paddingLeft: '32px' }} />
            </div>
          </div>
        </div>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>每周预算上限（元）</label>
          <div style={{ position: 'relative' }}>
            <span style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: '#b4aba2', fontSize: '15px' }}>¥</span>
            <input type="number" value={form.weekly_cap} min={0}
              onChange={e => setForm(prev => ({ ...prev, weekly_cap: parseFloat(e.target.value) || 0 }))}
              style={{ ...inputStyle, paddingLeft: '32px' }} />
          </div>
        </div>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>单餐预算下限（元）</label>
          <div style={{ position: 'relative' }}>
            <span style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: '#b4aba2', fontSize: '15px' }}>¥</span>
            <input type="number" value={form.min_meal_budget} min={0}
              onChange={e => setForm(prev => ({ ...prev, min_meal_budget: parseFloat(e.target.value) || 8 }))}
              style={{ ...inputStyle, paddingLeft: '32px' }} />
          </div>
        </div>
      </div>

      <button onClick={handleSave} disabled={loading}
        style={{
          width: '100%', marginTop: '20px', background: loading ? '#b4aba2' : '#f7663c',
          color: '#fff', border: 'none', borderRadius: '14px', padding: '14px',
          fontSize: '16px', fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
          boxShadow: loading ? 'none' : '0 4px 16px rgba(247,102,60,0.3)',
        }}>
        {loading ? '保存中...' : '保存预算设置'}
      </button>
    </div>
  )
}

export default BudgetForm
