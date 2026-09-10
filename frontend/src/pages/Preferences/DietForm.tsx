import React, { useEffect, useState } from 'react'
import { message } from 'antd'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

const CUISINE_OPTIONS = ['粤菜', '川菜', '江浙', '湘菜', '鲁菜', '轻食', '日料', '西餐', '东南亚', '东北菜']
const SPICE_LABELS = ['不吃辣', '微辣', '中辣', '重辣', '变态辣']
const FLAVOR_OPTIONS = ['清淡', '偏咸', '偏甜', '酸辣', '酱香']
const STAPLE_OPTIONS = ['米饭', '面食', '杂粮', '低碳']

const DietForm: React.FC = () => {
  const { summary, updateDiet } = usePreferenceStore()
  const [loading, setLoading] = useState(false)

  const [form, setForm] = useState({
    cuisines: [] as string[],
    spice_level: 1,
    flavor_preference: '清淡',
    staple_preference: '杂粮',
  })

  useEffect(() => {
    if (summary?.diet_preference) {
      const d = summary.diet_preference
      setForm({
        cuisines: d.cuisines ?? [],
        spice_level: d.spice_level,
        flavor_preference: d.flavor_preference || '清淡',
        staple_preference: d.staple_preference || '杂粮',
      })
    }
  }, [summary])

  const toggleCuisine = (c: string) => {
    setForm(prev => ({
      ...prev,
      cuisines: prev.cuisines.includes(c) ? prev.cuisines.filter(x => x !== c) : [...prev.cuisines, c],
    }))
  }

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateDiet(form)
      message.success('已保存饮食偏好')
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
        <span>🍽️</span> 饮食偏好
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>偏好菜系（可多选）</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {CUISINE_OPTIONS.map(c => (
              <span key={c} onClick={() => toggleCuisine(c)} style={{
                padding: '6px 14px', borderRadius: '20px', fontSize: '13px', cursor: 'pointer',
                border: form.cuisines.includes(c) ? '1px solid #f7663c' : '1px solid #d7d1c9',
                background: form.cuisines.includes(c) ? 'rgba(247,102,60,0.1)' : '#ece7e1',
                color: form.cuisines.includes(c) ? '#f7663c' : '#5c5650',
              }}>
                {c}
              </span>
            ))}
          </div>
        </div>
        <div>
          <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>辣度等级</label>
          <div style={{ display: 'flex', gap: '4px' }}>
            {SPICE_LABELS.map((label, i) => (
              <span key={i} onClick={() => setForm(prev => ({ ...prev, spice_level: i }))} style={{
                flex: 1, textAlign: 'center', padding: '10px 4px', borderRadius: '10px',
                fontSize: '12px', cursor: 'pointer',
                background: form.spice_level === i ? '#f7663c' : '#ece7e1',
                color: form.spice_level === i ? '#fff' : '#5c5650',
                fontWeight: form.spice_level === i ? 600 : 400,
              }}>
                {label}
              </span>
            ))}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>口味偏好</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {FLAVOR_OPTIONS.map(f => (
                <span key={f} onClick={() => setForm(prev => ({ ...prev, flavor_preference: f }))} style={{
                  padding: '6px 12px', borderRadius: '10px', fontSize: '13px', cursor: 'pointer',
                  background: form.flavor_preference === f ? '#f7663c' : '#ece7e1',
                  color: form.flavor_preference === f ? '#fff' : '#5c5650',
                }}>
                  {f}
                </span>
              ))}
            </div>
          </div>
          <div>
            <label style={{ fontSize: '13px', color: '#5c5650', marginBottom: '6px', display: 'block' }}>主食偏好</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {STAPLE_OPTIONS.map(s => (
                <span key={s} onClick={() => setForm(prev => ({ ...prev, staple_preference: s }))} style={{
                  padding: '6px 12px', borderRadius: '10px', fontSize: '13px', cursor: 'pointer',
                  background: form.staple_preference === s ? '#f7663c' : '#ece7e1',
                  color: form.staple_preference === s ? '#fff' : '#5c5650',
                }}>
                  {s}
                </span>
              ))}
            </div>
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
        {loading ? '保存中...' : '保存饮食偏好'}
      </button>
    </div>
  )
}

export default DietForm
