/**
 * 表单原语 (小程序端) - 与 H5 的 components/ui/form.tsx 同一套观感
 *
 * 小程序的 Input 没有受控 value 的坑, 但数字输入必须显式 type="digit"/"number",
 * 否则手机上弹的是全键盘。
 */
import type { ReactNode } from 'react'
import { Input, Text, Textarea, View } from '@tarojs/components'

import { cx } from './index'

export function Field(props: {
  label: string
  hint?: string
  children: ReactNode
  style?: Record<string, string | number>
}) {
  return (
    <View className="field" style={props.style}>
      <View className="field__label">{props.label}</View>
      {props.children}
      {props.hint ? <View className="field__hint">{props.hint}</View> : null}
    </View>
  )
}

export function NumberField(props: {
  label: string
  value: number | string
  onChange: (value: number) => void
  placeholder?: string
  hint?: string
  money?: boolean
  style?: Record<string, string | number>
}) {
  return (
    <Field label={props.label} hint={props.hint} style={props.style}>
      <Input
        className="text-input"
        type="digit"
        value={String(props.value ?? '')}
        placeholder={props.placeholder || '0'}
        onInput={(event) => props.onChange(Number(event.detail.value))}
      />
    </Field>
  )
}

export function TextField(props: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  hint?: string
  multiline?: boolean
}) {
  return (
    <Field label={props.label} hint={props.hint}>
      {props.multiline ? (
        <Textarea
          className="text-input"
          style={{ height: 88, padding: '12px 14px' }}
          value={props.value}
          placeholder={props.placeholder}
          onInput={(event) => props.onChange(event.detail.value)}
        />
      ) : (
        <Input
          className="text-input"
          value={props.value}
          placeholder={props.placeholder}
          onInput={(event) => props.onChange(event.detail.value)}
        />
      )}
    </Field>
  )
}

/** 单选/多选胶囊组; multiple=false 时是单选 */
export function ChipGroup(props: {
  label?: string
  hint?: string
  options: string[]
  selected: string[]
  multiple?: boolean
  onToggle?: (value: string) => void
  onChange?: (value: string) => void
}) {
  const { options, selected, multiple = true, onToggle, onChange } = props
  const body = (
    <View className="chip-row">
      {options.map((option) => {
        const on = selected.includes(option)
        return (
          <View
            key={option}
            className={cx('chip-option', 'tap', on && 'chip-option--on')}
            onClick={() => (multiple ? onToggle?.(option) : onChange?.(option))}
          >
            <Text>{option}</Text>
          </View>
        )
      })}
    </View>
  )
  if (!props.label) return body
  return (
    <Field label={props.label} hint={props.hint}>
      {body}
    </Field>
  )
}
