/**
 * 表单原语 - 偏好设置里 5 个表单共用, 避免每个表单各写一套内联样式
 */
import React from 'react'
import { Card, PillButton } from './index'

export const Field: React.FC<{
  label: string
  hint?: string
  tone?: 'default' | 'danger' | 'warn'
  children: React.ReactNode
}> = ({ label, hint, tone = 'default', children }) => (
  <div className="field">
    <label className={`field-label ${tone === 'default' ? '' : `is-${tone}`}`}>{label}</label>
    {children}
    {hint && <div className="field-hint">{hint}</div>}
  </div>
)

export const NumberInput: React.FC<{
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  placeholder?: string
  money?: boolean
  center?: boolean
}> = ({ value, onChange, min, max, placeholder, money, center }) => {
  const input = (
    <input
      className="text-input"
      type="number"
      inputMode="decimal"
      value={Number.isFinite(value) ? value : ''}
      min={min}
      max={max}
      placeholder={placeholder}
      style={center ? { textAlign: 'center', paddingLeft: 16 } : undefined}
      onChange={(event) => {
        const next = Number.parseFloat(event.target.value)
        onChange(Number.isFinite(next) ? next : 0)
      }}
    />
  )
  if (!money) return input
  return (
    <div className="text-input-wrap">
      <span className="text-input-prefix">¥</span>
      {input}
    </div>
  )
}

export const TextInput: React.FC<{
  value: string
  onChange: (value: string) => void
  placeholder?: string
  onEnter?: () => void
}> = ({ value, onChange, placeholder, onEnter }) => (
  <input
    className="text-input"
    value={value}
    placeholder={placeholder}
    onChange={(event) => onChange(event.target.value)}
    onKeyDown={(event) => {
      if (event.key === 'Enter' && onEnter) {
        event.preventDefault()
        onEnter()
      }
    }}
  />
)

/** 单选/多选都用同一套胶囊, 选中态是黑底白字 */
export const ChipSelect: React.FC<{
  options: Array<{ value: string; label: string }>
  selected: string[]
  onToggle: (value: string) => void
  fill?: boolean
}> = ({ options, selected, onToggle, fill }) => (
  <div className={`chip-row ${fill ? 'is-fill' : ''}`}>
    {options.map((option) => (
      <button
        key={option.value}
        type="button"
        className={`chip-option ${selected.includes(option.value) ? 'is-on' : ''}`}
        onClick={() => onToggle(option.value)}
      >
        {option.label}
      </button>
    ))}
  </div>
)

export const RatioBar: React.FC<{
  segments: Array<{ value: number; color: string }>
}> = ({ segments }) => (
  <div className="ratio-bar">
    {segments.map((segment, index) => (
      <i
        key={index}
        style={{ flex: Math.max(segment.value, 0.001), background: segment.color }}
      />
    ))}
  </div>
)

export const FormCard: React.FC<{
  title: string
  subtitle?: string
  saving?: boolean
  saveLabel: string
  disabled?: boolean
  onSave: () => void
  children: React.ReactNode
}> = ({ title, subtitle, saving, saveLabel, disabled, onSave, children }) => (
  <Card>
    <div className="card-head">
      <div>
        <div className="card-title">{title}</div>
        {subtitle && <div className="card-sub">{subtitle}</div>}
      </div>
    </div>
    <div className="form-stack">{children}</div>
    <div style={{ marginTop: 20 }}>
      <PillButton block loading={saving} disabled={disabled} onClick={onSave}>
        {saveLabel}
      </PillButton>
    </div>
  </Card>
)
