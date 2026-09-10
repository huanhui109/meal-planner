import React, { useEffect, useState } from 'react'
import { message } from 'antd'
import { Field, FormCard, NumberInput } from '../../components/ui/form'
import { Banner } from '../../components/ui'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

const BudgetForm: React.FC = () => {
  const { summary, updateBudget } = usePreferenceStore()
  const [loading, setLoading] = useState(false)

  const [form, setForm] = useState({
    weekday_daily_budget: 35,
    weekend_daily_budget: 80,
    weekly_cap: 350,
    min_meal_budget: 8,
    takeout_reference_price: 26,
  })

  useEffect(() => {
    if (summary?.budget) {
      const b = summary.budget
      setForm({
        weekday_daily_budget: b.weekday_daily_budget || 35,
        weekend_daily_budget: b.weekend_daily_budget || 80,
        weekly_cap: b.weekly_cap || 350,
        min_meal_budget: b.min_meal_budget ?? 8,
        takeout_reference_price: b.takeout_reference_price ?? 26,
      })
    }
  }, [summary])

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateBudget(form)
      message.success('已保存预算')
    } catch (e) {
      message.error((e as Error).message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <FormCard
      title="预算"
      subtitle="AI 会按食材参考价控制每餐成本, 超支只提醒不阻断"
      saving={loading}
      saveLabel="保存预算设置"
      onSave={handleSave}
    >
      <Banner
        tone="info"
        title="预算怎么用"
        text="工作日与周末分开设, 周上限用于整周校验; 单餐下限避免某餐被压得太低。"
      />

      <div className="field-grid">
        <Field label="工作日每日预算 (元)">
          <NumberInput
            money
            value={form.weekday_daily_budget}
            min={5}
            onChange={(value) =>
              setForm((prev) => ({ ...prev, weekday_daily_budget: value || 35 }))
            }
          />
        </Field>
        <Field label="周末每日预算 (元)">
          <NumberInput
            money
            value={form.weekend_daily_budget}
            min={5}
            onChange={(value) =>
              setForm((prev) => ({ ...prev, weekend_daily_budget: value || 80 }))
            }
          />
        </Field>
      </div>

      <Field label="每周预算上限 (元)">
        <NumberInput
          money
          value={form.weekly_cap}
          min={0}
          onChange={(value) => setForm((prev) => ({ ...prev, weekly_cap: value }))}
        />
      </Field>

      <Field label="单餐预算下限 (元)" hint="低于这个金额的一餐会被提示, 避免只吃主食">
        <NumberInput
          money
          value={form.min_meal_budget}
          min={0}
          onChange={(value) => setForm((prev) => ({ ...prev, min_meal_budget: value }))}
        />
      </Field>

      <Field
        label="一顿外卖的参考价 (元)"
        hint="今日页的「自做 vs 外卖」按它估算; 在卡片上改价也会写回这里"
      >
        <NumberInput
          money
          value={form.takeout_reference_price}
          min={0}
          max={500}
          onChange={(value) =>
            setForm((prev) => ({ ...prev, takeout_reference_price: value }))
          }
        />
      </Field>
    </FormCard>
  )
}

export default BudgetForm
