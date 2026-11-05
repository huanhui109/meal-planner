import { useEffect, useRef, useState } from 'react'
import { Alert, Modal } from 'antd'
import { MinusOutlined, PlusOutlined } from '@ant-design/icons'
import type { MealContext } from '@shared/meal'

interface Props {
  open: boolean
  context: MealContext
  busy: boolean
  error?: string
  onClose: () => void
  onApply: (context: MealContext) => Promise<boolean>
}

export default function MealConditions({ open, context, busy, error, onClose, onApply }: Props) {
  const [draft, setDraft] = useState(context)
  const [avoid, setAvoid] = useState('')
  const wasOpen = useRef(false)
  useEffect(() => {
    if (open && !wasOpen.current) {
      setDraft(context)
      setAvoid(context.avoid.join('、'))
    }
    wasOpen.current = open
  }, [open, context])
  const update = <K extends keyof MealContext>(key: K, value: MealContext[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  return (
    <Modal open={open} title="这一餐的条件" footer={null} onCancel={onClose} width={480}>
      <form className="meal-form" onSubmit={(event) => {
        event.preventDefault()
        void onApply({
          ...draft, avoid: avoid.split(/[、,，\n]/).map((word) => word.trim()).filter(Boolean),
        }).then((ok) => { if (ok) onClose() })
      }}>
        {error && <Alert type="warning" showIcon message={error} />}
        <div className="meal-field">
          <span>几个人吃</span>
          <div className="meal-stepper">
            <button type="button" className="meal-icon" title="减少人数" aria-label="减少人数"
              disabled={draft.servings <= 1 || busy} onClick={() => update('servings', draft.servings - 1)}>
              <MinusOutlined />
            </button>
            <output>{draft.servings}<small>人</small></output>
            <button type="button" className="meal-icon" title="增加人数" aria-label="增加人数"
              disabled={draft.servings >= 20 || busy} onClick={() => update('servings', draft.servings + 1)}>
              <PlusOutlined />
            </button>
          </div>
        </div>
        <label className="meal-field">
          <span>做饭时间上限</span>
          <select value={draft.max_minutes} disabled={busy}
            onChange={(event) => update('max_minutes', Number(event.target.value))}>
            {Array.from(new Set([15, 20, 30, 45, 60, 90, 120, 180, draft.max_minutes])).sort((a, b) => a - b)
              .map((minutes) => <option key={minutes} value={minutes}>{minutes} 分钟</option>)}
          </select>
        </label>
        <label className="meal-field">
          <span>整餐预算目标</span>
          <div className="meal-number"><span>¥</span><input aria-label="整餐预算目标"
            type="number" min="1" max="5000" step="1" placeholder="不限" value={draft.budget ?? ''}
            disabled={busy} onChange={(event) => update('budget', event.target.value ? Number(event.target.value) : null)} /></div>
        </label>
        <label className="meal-field">
          <span>辣度</span>
          <select value={draft.max_spice} disabled={busy}
            onChange={(event) => update('max_spice', Number(event.target.value))}>
            {['不辣', '微辣', '中辣', '较辣', '不限'].map((label, value) =>
              <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="meal-field meal-field-stack">
          <span>这一餐不吃</span>
          <input value={avoid} maxLength={500} placeholder="香菜、花生……" disabled={busy}
            onChange={(event) => setAvoid(event.target.value)} />
        </label>
        {([
          ['vegetarian', '不吃肉'],
          ['light', '清淡一点'],
          ['use_fridge', '优先用家里食材'],
          ['avoid_recent', '避开近七天吃过的'],
        ] as const).map(([key, label]) =>
          <label className="meal-field" key={key}>
            <span>{label}</span>
            <input type="checkbox" role="switch" checked={draft[key]} disabled={busy}
              onChange={(event) => update(key, event.target.checked)} />
          </label>)}
        <button type="submit" className="meal-button meal-primary" disabled={busy}>
          {busy ? '正在安排…' : '按这些条件安排'}
        </button>
      </form>
    </Modal>
  )
}
