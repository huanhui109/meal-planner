import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Skeleton } from 'antd'
import { ArrowLeftOutlined, CheckOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons'
import { getPreferenceSummary, updateAllergy, updateDiet, updateHousehold } from '../../api/preferences'
import type { UserPreferenceSummary } from '../../types'

const split = (text: string) => text.split(/[、,，\n]/).map((word) => word.trim()).filter(Boolean)

export default function MealPreferences() {
  const [summary, setSummary] = useState<UserPreferenceSummary | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [saved, setSaved] = useState('')
  const [servings, setServings] = useState(1)
  const [minutes, setMinutes] = useState(30)
  const [spice, setSpice] = useState(2)
  const [allergens, setAllergens] = useState('')
  const [avoid, setAvoid] = useState('')
  const [other, setOther] = useState('')
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getPreferenceSummary()
      setSummary(data)
      setServings(data.household?.member_count ?? 1)
      setMinutes(data.household?.weekday_cook_minutes ?? 30)
      setSpice(Math.min(4, data.diet_preference?.spice_level ?? 2))
      setAllergens(data.allergy_restriction?.allergens.join('、') ?? '')
      setAvoid(data.allergy_restriction?.avoid_ingredients.join('、') ?? '')
      setOther(data.allergy_restriction?.dietary_restrictions ?? '')
      setError('')
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  const save = async (group: string, operation: () => Promise<unknown>) => {
    setBusy(group); setSaved(''); setError('')
    try { await operation(); setSaved(group) }
    catch (err) { setError((err as Error).message) }
    finally { setBusy('') }
  }
  const submit = (group: string) => <button type="submit" className="meal-button" disabled={Boolean(busy)}>
    {saved === group ? <CheckOutlined /> : <SaveOutlined />}{busy === group ? '正在保存…' : saved === group ? '已保存' : '保存'}</button>
  return <div className="meal-page meal-settings">
    <header className="meal-page-heading"><div><div className="meal-eyebrow">长期记住的习惯</div><h1>家人的口味</h1></div>
      <Link to="/me" className="meal-icon" aria-label="返回设置" title="返回设置"><ArrowLeftOutlined /></Link></header>
    {error && <Alert message={error} type="error" showIcon action={!summary && <button type="button" className="meal-icon"
      aria-label="重新读取偏好" onClick={() => { void load() }}><ReloadOutlined /></button>} />}
    {loading ? <Skeleton active /> : summary && <>
      <form className="meal-settings-section meal-form" onSubmit={(event) => {
        event.preventDefault()
        void save('household', () => updateHousehold({
          ...(summary.household ?? {}), member_count: servings, weekday_cook_minutes: minutes,
        }))
      }} onChange={() => setSaved('')}>
        <h2>家庭与时间</h2>
        <label className="meal-field"><span>通常几个人吃</span><input type="number" min="1" max="20" required
          value={servings} onChange={(event) => setServings(Number(event.target.value))} /></label>
        <label className="meal-field"><span>工作日做饭时间</span><select value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}>
          {Array.from(new Set([15, 20, 30, 45, 60, 90, 120, 180, minutes])).sort((a, b) => a - b)
            .map((value) => <option key={value} value={value}>{value} 分钟</option>)}
        </select></label>
        {submit('household')}
      </form>
      <form className="meal-settings-section meal-form" onSubmit={(event) => {
        event.preventDefault()
        void save('diet', () => updateDiet({
          ...(summary.diet_preference ?? {}), cuisines: summary.diet_preference?.cuisines.length ? summary.diet_preference.cuisines : ['家常'],
          spice_level: spice,
        }))
      }} onChange={() => setSaved('')}>
        <h2>辣度偏好</h2>
        <label className="meal-field"><span>能接受的辣度</span><select value={spice} onChange={(event) => setSpice(Number(event.target.value))}>
          {['不辣', '微辣', '中辣', '较辣', '不限'].map((text, value) => <option key={value} value={value}>{text}</option>)}
        </select></label>
        {submit('diet')}
      </form>
      <form className="meal-settings-section meal-form" onSubmit={(event) => {
        event.preventDefault()
        void save('allergy', () => updateAllergy({
          allergens: split(allergens), avoid_ingredients: split(avoid), dietary_restrictions: other,
        }))
      }} onChange={() => setSaved('')}>
        <h2>过敏与长期忌口</h2>
        <label className="meal-field meal-field-stack"><span>过敏食材</span><input value={allergens} maxLength={400}
          placeholder="花生、虾" onChange={(event) => setAllergens(event.target.value)} /></label>
        <label className="meal-field meal-field-stack"><span>不吃的食材</span><input value={avoid} maxLength={400}
          placeholder="香菜、牛肉" onChange={(event) => setAvoid(event.target.value)} /></label>
        {other && <label className="meal-field meal-field-stack"><span>原有饮食限制</span><input value={other} maxLength={400}
          onChange={(event) => setOther(event.target.value)} /></label>}
        {submit('allergy')}
      </form>
    </>}
  </div>
}
