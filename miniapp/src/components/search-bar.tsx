/**
 * 搜索框 (audit T3.4) - 300ms debounce, 受控输入 + 清空按钮
 *
 * 在周菜单页顶部过滤菜品, 在冰箱页按食材搜菜谱
 */
import { useEffect, useRef, useState } from 'react'
import { Input, Text, View } from '@tarojs/components'

interface Props {
  placeholder?: string
  value?: string
  onChange: (value: string) => void
  debounceMs?: number
}

export function SearchBar({ placeholder = '搜索', value: controlled, onChange, debounceMs = 300 }: Props) {
  const [inner, setInner] = useState(controlled ?? '')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 外部受控值变了同步进来 (例如清空按钮)
  useEffect(() => {
    if (controlled !== undefined && controlled !== inner) setInner(controlled)
  }, [controlled])

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [])

  const emit = (next: string) => {
    setInner(next)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => onChange(next.trim()), debounceMs)
  }

  return (
    <View className="search-bar">
      <Text className="search-bar__icon">🔍</Text>
      <Input
        className="search-bar__input text-input"
        value={inner}
        placeholder={placeholder}
        placeholderStyle="color: var(--color-ink3)"
        confirmType="search"
        onInput={(e) => emit(e.detail.value)}
      />
      {inner ? (
        <Text
          className="search-bar__clear tap"
          onClick={() => {
            if (timer.current) clearTimeout(timer.current)
            setInner('')
            onChange('')
          }}
        >
          清空
        </Text>
      ) : null}
    </View>
  )
}

export default SearchBar
