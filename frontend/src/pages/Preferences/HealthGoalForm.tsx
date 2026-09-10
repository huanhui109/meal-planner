import React, { useEffect, useState } from 'react'
import { message } from 'antd'
import { ChipSelect, Field, FormCard, NumberInput, RatioBar } from '../../components/ui/form'
import { usePreferenceStore } from '../../stores/usePreferenceStore'
import { formatPercent } from '@shared/format'
import { tokens } from '@shared/tokens'

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
    } catch (e) {
      message.error((e as Error).message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  const total = form.protein_pct + form.carb_pct + form.fat_pct
  const balanced = total === 100

  return (
    <FormCard
      title="目标与比例"
      subtitle="按日校验热量与三大营养素供能比"
      saving={loading}
      saveLabel={balanced ? '保存健康目标' : `营养比例需等于 100%（当前 ${total}%）`}
      disabled={!balanced}
      onSave={handleSave}
    >
      <Field label="目标类型">
        <ChipSelect
          options={GOAL_OPTIONS.map((item) => ({ value: item, label: item }))}
          selected={[form.goal_type]}
          onToggle={(value) => setForm((prev) => ({ ...prev, goal_type: value }))}
        />
      </Field>

      <Field label="每日目标热量 (千卡)">
        <NumberInput
          value={form.daily_calories}
          min={800}
          max={5000}
          onChange={(value) => setForm((prev) => ({ ...prev, daily_calories: value || 2000 }))}
        />
      </Field>

      <Field label="营养比例">
        <RatioBar
          segments={[
            { value: form.protein_pct, color: tokens.color.ink },
            { value: form.carb_pct, color: tokens.color.ink3 },
            { value: form.fat_pct, color: tokens.color.accent },
          ]}
        />
        <div className={`ratio-legend ${balanced ? 'is-ok' : 'is-bad'}`}>
          <span>蛋白 {formatPercent(form.protein_pct)}</span>
          <span>碳水 {formatPercent(form.carb_pct)}</span>
          <span>脂肪 {formatPercent(form.fat_pct)}</span>
          <span>{balanced ? '合计 100% ✓' : `合计 ${total}%`}</span>
        </div>
        <div className="field-grid is-triple">
          {(['protein_pct', 'carb_pct', 'fat_pct'] as const).map((key) => (
            <NumberInput
              key={key}
              center
              value={form[key]}
              min={10}
              max={70}
              onChange={(value) => setForm((prev) => ({ ...prev, [key]: value }))}
            />
          ))}
        </div>
      </Field>
    </FormCard>
  )
}

export default HealthGoalForm
