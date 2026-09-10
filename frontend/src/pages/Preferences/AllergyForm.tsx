import React, { useEffect, useState } from 'react'
import { message } from 'antd'
import { Field, FormCard, TextInput } from '../../components/ui/form'
import { usePreferenceStore } from '../../stores/usePreferenceStore'

type ListKey = 'allergens' | 'avoid_ingredients'

const AllergyForm: React.FC = () => {
  const { summary, updateAllergy } = usePreferenceStore()
  const [loading, setLoading] = useState(false)
  const [allergenInput, setAllergenInput] = useState('')
  const [avoidInput, setAvoidInput] = useState('')

  const [form, setForm] = useState({
    allergens: [] as string[],
    avoid_ingredients: [] as string[],
    dietary_restrictions: '',
  })

  useEffect(() => {
    if (summary?.allergy_restriction) {
      const a = summary.allergy_restriction
      setForm({
        allergens: a.allergens ?? [],
        avoid_ingredients: a.avoid_ingredients ?? [],
        dietary_restrictions: a.dietary_restrictions || '',
      })
    }
  }, [summary])

  const removeItem = (key: ListKey, item: string) => {
    setForm((prev) => ({ ...prev, [key]: prev[key].filter((value) => value !== item) }))
  }

  const addItem = (key: ListKey, value: string) => {
    const text = value.trim()
    if (!text) return
    setForm((prev) => (prev[key].includes(text) ? prev : { ...prev, [key]: [...prev[key], text] }))
    if (key === 'allergens') setAllergenInput('')
    else setAvoidInput('')
  }

  const handleSave = async () => {
    setLoading(true)
    try {
      await updateAllergy(form)
      message.success('已保存忌口设置')
    } catch (e) {
      message.error((e as Error).message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <FormCard
      title="过敏与忌口"
      subtitle="过敏源是硬过滤, 命中整道菜都会被剔除"
      saving={loading}
      saveLabel="保存忌口设置"
      onSave={handleSave}
    >
      <Field label="过敏源" tone="danger" hint="绝对禁止出现, 例如: 花生、芒果、虾">
        {form.allergens.length > 0 && (
          <div className="chip-row">
            {form.allergens.map((item) => (
              <button
                key={item}
                type="button"
                className="chip-option is-remove is-danger"
                onClick={() => removeItem('allergens', item)}
              >
                {item} ✕
              </button>
            ))}
          </div>
        )}
        <div className="inline-add">
          <TextInput
            value={allergenInput}
            onChange={setAllergenInput}
            placeholder="输入过敏源后回车或点添加"
            onEnter={() => addItem('allergens', allergenInput)}
          />
          <button
            type="button"
            className="pill pill--gray pill--sm"
            onClick={() => addItem('allergens', allergenInput)}
          >
            添加
          </button>
        </div>
      </Field>

      <Field label="忌口食材" tone="warn" hint="尽量避免, 例如: 香菜、动物内脏">
        {form.avoid_ingredients.length > 0 && (
          <div className="chip-row">
            {form.avoid_ingredients.map((item) => (
              <button
                key={item}
                type="button"
                className="chip-option is-remove is-warn"
                onClick={() => removeItem('avoid_ingredients', item)}
              >
                {item} ✕
              </button>
            ))}
          </div>
        )}
        <div className="inline-add">
          <TextInput
            value={avoidInput}
            onChange={setAvoidInput}
            placeholder="输入忌口食材后回车或点添加"
            onEnter={() => addItem('avoid_ingredients', avoidInput)}
          />
          <button
            type="button"
            className="pill pill--gray pill--sm"
            onClick={() => addItem('avoid_ingredients', avoidInput)}
          >
            添加
          </button>
        </div>
      </Field>

      <Field label="饮食习惯" hint="例如: 清真、素食、不吃牛肉">
        <TextInput
          value={form.dietary_restrictions}
          onChange={(value) => setForm((prev) => ({ ...prev, dietary_restrictions: value }))}
          placeholder="如清真、素食等"
        />
      </Field>
    </FormCard>
  )
}

export default AllergyForm
