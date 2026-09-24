import React, { useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import { ChipSelect, Field, FormCard } from '../../components/ui/form'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

const CUISINE_OPTIONS = ['粤菜', '川菜', '江浙', '湘菜', '鲁菜', '轻食', '日料', '西餐', '东南亚', '东北菜']
const SPICE_LABELS = ['不吃辣', '微辣', '中辣', '重辣', '变态辣']
const FLAVOR_OPTIONS = ['清淡', '偏咸', '偏甜', '酸辣', '酱香']
const STAPLE_OPTIONS = ['米饭', '面食', '杂粮', '低碳']

const DietForm: React.FC = () => {
  const { summary, syncToken, updateDiet } = usePreferenceStore()
  const [loading, setLoading] = useState(false)

  /** 已同步过的 syncToken, -1 表示还没同步过 */
  const syncedRef = useRef(-1)

  const [form, setForm] = useState({
    cuisines: [] as string[],
    spice_level: 1,
    flavor_preference: '清淡',
    staple_preference: '杂粮',
  })

  useEffect(() => {
    // 只在真正从服务端重新拉取时同步一次: 保存别的卡片不应该覆盖这张卡正在编辑的内容
    if (syncedRef.current === syncToken) return
    syncedRef.current = syncToken
    if (summary?.diet_preference) {
      const d = summary.diet_preference
      setForm({
        cuisines: d.cuisines ?? [],
        spice_level: d.spice_level,
        flavor_preference: d.flavor_preference || '清淡',
        staple_preference: d.staple_preference || '杂粮',
      })
    }
  }, [syncToken, summary])

  const toggleCuisine = (cuisine: string) => {
    setForm((prev) => ({
      ...prev,
      cuisines: prev.cuisines.includes(cuisine)
        ? prev.cuisines.filter((item) => item !== cuisine)
        : [...prev.cuisines, cuisine],
    }))
  }

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateDiet(form)
      message.success('已保存饮食偏好')
    } catch (e) {
      message.error((e as Error).message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <FormCard
      title="口味与偏好"
      subtitle="菜系与辣度会直接影响生成的菜"
      saving={loading}
      saveLabel="保存饮食偏好"
      onSave={handleSave}
    >
      <Field label="偏好菜系" hint="可多选, 不选则由 AI 自由搭配">
        <ChipSelect
          options={CUISINE_OPTIONS.map((item) => ({ value: item, label: item }))}
          selected={form.cuisines}
          onToggle={toggleCuisine}
        />
      </Field>

      <Field label="辣度">
        <ChipSelect
          fill
          options={SPICE_LABELS.map((label, index) => ({ value: String(index), label }))}
          selected={[String(form.spice_level)]}
          onToggle={(value) => setForm((prev) => ({ ...prev, spice_level: Number(value) }))}
        />
      </Field>

      <div className="field-grid">
        <Field label="口味偏好">
          <ChipSelect
            options={FLAVOR_OPTIONS.map((item) => ({ value: item, label: item }))}
            selected={[form.flavor_preference]}
            onToggle={(value) => setForm((prev) => ({ ...prev, flavor_preference: value }))}
          />
        </Field>
        <Field label="主食偏好">
          <ChipSelect
            options={STAPLE_OPTIONS.map((item) => ({ value: item, label: item }))}
            selected={[form.staple_preference]}
            onToggle={(value) => setForm((prev) => ({ ...prev, staple_preference: value }))}
          />
        </Field>
      </div>
    </FormCard>
  )
}

export default DietForm
