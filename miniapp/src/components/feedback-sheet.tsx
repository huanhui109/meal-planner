/**
 * F8 反馈 sheet (小程序) - 与 H5 的 FeedbackSheet 同一套
 *
 * 4 类目 (bug / suggestion / recipe / other) + 文字 + 联系方式 (可选) + 设备信息
 * 匿名可提交 (未登录时也能用), 后端限流 24h 5 条
 */
import { useMemo, useState } from 'react'
import Taro from '@tarojs/taro'
import { Input, ScrollView, Text, Textarea, View } from '@tarojs/components'

import { PillButton } from './ui'
import { submitFeedback, type FeedbackCategory } from '../lib/api'
import { toast } from '../lib/nav'

interface Props {
  open: boolean
  onClose: () => void
}

const CATEGORY_OPTIONS: Array<{ value: FeedbackCategory; label: string; hint: string }> = [
  { value: 'bug', label: '功能异常', hint: '闪退 / 报错 / 加载失败' },
  { value: 'suggestion', label: '产品建议', hint: '想要但还没做的功能' },
  { value: 'recipe', label: '菜谱纠错', hint: '食材/步骤/口味不对' },
  { value: 'other', label: '其它', hint: '任何想跟我们说的话' },
]

const PLATFORM_INFO = (() => {
  try {
    const info = Taro.getSystemInfoSync()
    return {
      platform: info.platform || 'unknown',
      system: info.system || '',
      version: info.version || '',
      model: info.model || '',
    }
  } catch {
    return { platform: 'unknown', system: '', version: '', model: '' }
  }
})()

export function FeedbackSheet({ open, onClose }: Props) {
  const [category, setCategory] = useState<FeedbackCategory>('bug')
  const [content, setContent] = useState('')
  const [contact, setContact] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const deviceInfo = useMemo(() => JSON.stringify(PLATFORM_INFO), [])

  if (!open) return null

  const reset = () => {
    setCategory('bug')
    setContent('')
    setContact('')
    setError('')
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const handleSubmit = async () => {
    const trimmed = content.trim()
    if (trimmed.length < 1) {
      setError('请描述一下遇到的问题或建议')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      await submitFeedback({
        category,
        content: trimmed,
        contact: contact.trim() || undefined,
        device_info: deviceInfo,
      })
      toast('已收到, 谢谢反馈')
      handleClose()
    } catch (err) {
      const message = (err as Error).message || '提交失败, 请稍后再试'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <View className="sheet">
      <View className="sheet__mask" onClick={handleClose} />
      <View className="sheet__panel">
        <View className="sheet__head">
          <Text className="sheet__title">意见反馈</Text>
          <Text className="sheet__close tap" onClick={handleClose}>
            关闭
          </Text>
        </View>

        <ScrollView scrollY className="sheet__body">
          <View className="fb-section">
            <Text className="fb-section__label">反馈类型</Text>
            <View className="fb-cat">
              {CATEGORY_OPTIONS.map((opt) => (
                <View
                  key={opt.value}
                  className={`fb-cat__opt ${category === opt.value ? 'fb-cat__opt--active' : ''}`}
                  onClick={() => setCategory(opt.value)}
                >
                  <Text className="fb-cat__label">{opt.label}</Text>
                  <Text className="fb-cat__hint">{opt.hint}</Text>
                </View>
              ))}
            </View>
          </View>

          <View className="fb-section">
            <Text className="fb-section__label">详细描述</Text>
            <Textarea
              className="fb-textarea"
              value={content}
              placeholder="尽量描述清楚场景 (在哪一步/点了什么按钮/出现什么现象), 我们就能更快定位"
              maxlength={2000}
              autoHeight
              onInput={(event) => setContent(event.detail.value)}
            />
            <Text className="fb-counter">{content.length} / 2000</Text>
          </View>

          <View className="fb-section">
            <Text className="fb-section__label">联系方式 (可选)</Text>
            <Input
              className="text-input"
              value={contact}
              placeholder="邮箱 / 微信号, 希望回复我们才填"
              maxlength={100}
              onInput={(event) => setContact(event.detail.value)}
            />
          </View>

          {error ? <View className="sheet__notice">{error}</View> : null}
        </ScrollView>

        <View className="sheet__foot">
          <PillButton block disabled={submitting} onClick={handleSubmit}>
            {submitting ? '提交中…' : '提交反馈'}
          </PillButton>
        </View>
      </View>
    </View>
  )
}

export default FeedbackSheet
