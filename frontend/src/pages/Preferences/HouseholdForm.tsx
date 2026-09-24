import React, { useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import { ChipSelect, Field, FormCard, NumberInput } from '../../components/ui/form'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

const EQUIPMENT_OPTIONS = [
  '灶台', '蒸锅', '空气炸锅', '微波炉', '烤箱',
  '电饭煲', '压力锅', '破壁机', '电磁炉', '榨汁机',
]

const HouseholdForm: React.FC = () => {
  const { summary, syncToken, updateHousehold } = usePreferenceStore()
  const [loading, setLoading] = useState(false)

  /** 已同步过的 syncToken, -1 表示还没同步过 */
  const syncedRef = useRef(-1)

  const [form, setForm] = useState({
    member_count: 1,
    meals_per_day: 2,
    kitchen_equipments: [] as string[],
    weekday_cook_minutes: 30,
    weekend_cook_minutes: 60,
  })

  useEffect(() => {
    // 只在真正从服务端重新拉取时同步一次: 保存别的卡片不应该覆盖这张卡正在编辑的内容
    if (syncedRef.current === syncToken) return
    syncedRef.current = syncToken
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
  }, [syncToken, summary])

  const toggleEquipment = (eq: string) => {
    setForm((prev) => ({
      ...prev,
      kitchen_equipments: prev.kitchen_equipments.includes(eq)
        ? prev.kitchen_equipments.filter((item) => item !== eq)
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

  return (
    <FormCard
      title="家庭与厨房"
      subtitle="决定每餐分量和能用的厨具"
      saving={loading}
      saveLabel="保存家庭信息"
      onSave={handleSave}
    >
      <div className="field-grid">
        <Field label="家庭人数">
          <NumberInput
            value={form.member_count}
            min={1}
            max={20}
            onChange={(value) => setForm((prev) => ({ ...prev, member_count: value || 1 }))}
          />
        </Field>
        <Field label="每日餐次">
          <NumberInput
            value={form.meals_per_day}
            min={1}
            max={5}
            onChange={(value) => setForm((prev) => ({ ...prev, meals_per_day: value || 2 }))}
          />
        </Field>
      </div>

      <Field label="厨房设备" hint="没有的设备不会排进菜单, 例如没烤箱就不会出现烘焙菜">
        <ChipSelect
          options={EQUIPMENT_OPTIONS.map((item) => ({ value: item, label: item }))}
          selected={form.kitchen_equipments}
          onToggle={toggleEquipment}
        />
      </Field>

      <div className="field-grid">
        <Field label="工作日做饭 (分钟)">
          <NumberInput
            value={form.weekday_cook_minutes}
            min={5}
            max={180}
            onChange={(value) => setForm((prev) => ({ ...prev, weekday_cook_minutes: value || 30 }))}
          />
        </Field>
        <Field label="周末做饭 (分钟)">
          <NumberInput
            value={form.weekend_cook_minutes}
            min={5}
            max={300}
            onChange={(value) => setForm((prev) => ({ ...prev, weekend_cook_minutes: value || 60 }))}
          />
        </Field>
      </div>
    </FormCard>
  )
}

export default HouseholdForm
