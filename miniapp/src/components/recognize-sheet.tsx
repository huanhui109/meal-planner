/**
 * F5.1 拍照识别入库 (小程序)
 *
 * 与 H5 的 components/RecognizePanel 同一套流程: 拍照 -> 模型识别 -> 候选清单
 * 逐条可改 -> 「全部入库」才写库。识别一定会错, 所以给的是草稿而不是结果。
 */
import { useState } from 'react'
import { Input, ScrollView, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { formatPercent } from '@shared/format'
import type { RecognitionItem, RecognitionResult } from '@shared/types'

import { PillButton } from './ui'
import { recognizeInventory } from '../lib/api'
import { toast } from '../lib/nav'

interface Props {
  open: boolean
  onClose: () => void
  onConfirm: (items: RecognitionItem[]) => Promise<void> | void
}

export function RecognizeSheet({ open, onClose, onConfirm }: Props) {
  const [result, setResult] = useState<RecognitionResult | null>(null)
  const [items, setItems] = useState<RecognitionItem[]>([])
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')

  if (!open) return null

  const reset = () => {
    setResult(null)
    setItems([])
    setNotice('')
  }

  const handleTake = async () => {
    try {
      let filePath = ''
      // chooseMedia 需要基础库 2.10.0+; 老版本回退到 chooseImage, 保证拍照/相册都能用
      if (Taro.chooseMedia) {
        const media = await Taro.chooseMedia({
          count: 1,
          mediaType: ['image'],
          sourceType: ['camera', 'album'],
          sizeType: ['compressed'],
        })
        filePath = media.tempFiles?.[0]?.tempFilePath || ''
      } else {
        const media = await Taro.chooseImage({
          count: 1,
          sourceType: ['camera', 'album'],
          sizeType: ['compressed'],
        })
        filePath = media.tempFilePaths?.[0] || ''
      }
      if (!filePath) return
      setBusy(true)
      setNotice('')
      const data = await recognizeInventory(filePath)
      setResult(data)
      setItems(data.items ?? [])
      if ((data.items ?? []).length === 0) setNotice('没认出食材, 换个角度再拍一张')
    } catch (err) {
      const message = (err as Error).message || ''
      if (message.includes('cancel')) return
      setNotice(message)
    } finally {
      setBusy(false)
    }
  }

  const patch = (index: number, next: Partial<RecognitionItem>) =>
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, ...next } : item)))

  const handleConfirm = async () => {
    const valid = items.filter((item) => item.name.trim() && item.quantity != null)
    if (valid.length === 0) {
      toast('至少填一样食材的名称和数量')
      return
    }
    setSaving(true)
    try {
      await onConfirm(valid)
      reset()
    } finally {
      setSaving(false)
    }
  }

  return (
    <View className="sheet">
      <View className="sheet__mask" onClick={onClose} />
      <View className="sheet__panel">
        <View className="sheet__head">
          <Text className="sheet__title">拍照入库</Text>
          <Text className="sheet__close tap" onClick={onClose}>
            关闭
          </Text>
        </View>

        <ScrollView scrollY className="sheet__body">
          <PillButton block variant="gray" disabled={busy} onClick={handleTake}>
            {busy ? '正在识别…' : items.length ? '换一张重新识别' : '拍一张冰箱 / 食材照片'}
          </PillButton>
          <View className="sheet__hint">识别出的只是草稿, 确认后才会入库</View>

          {!!notice && <View className="sheet__notice">{notice}</View>}

          {result ? (
            <View className="sheet__hint">
              识别出 {items.length} 样
              {result.model ? ` · ${result.model}` : ''} · 今日已用 {result.used_today}/
              {result.daily_limit} 次
            </View>
          ) : null}

          {items.map((item, index) => (
            <View key={index} className="recog-row">
              <Input
                className="text-input"
                value={item.name}
                placeholder="食材名称"
                onInput={(event) => patch(index, { name: event.detail.value })}
              />
              <Input
                className="text-input recog-row__num"
                type="digit"
                value={item.quantity == null ? '' : String(item.quantity)}
                placeholder="数量"
                onInput={(event) =>
                  patch(index, {
                    quantity: event.detail.value === '' ? null : Number(event.detail.value),
                  })
                }
              />
              <Input
                className="text-input recog-row__unit"
                value={item.unit}
                placeholder="单位"
                onInput={(event) => patch(index, { unit: event.detail.value })}
              />
              <Text className="recog-row__del tap" onClick={() => setItems((prev) => prev.filter((_, i) => i !== index))}>
                删除
              </Text>
              {item.confidence != null ? (
                <Text className="recog-row__conf">
                  置信 {formatPercent(item.confidence * 100)}
                  {item.known === false ? ' · 新食材' : ''}
                </Text>
              ) : null}
            </View>
          ))}
        </ScrollView>

        {items.length > 0 ? (
          <View className="sheet__foot">
            <PillButton block disabled={saving} onClick={handleConfirm}>
              {saving ? '入库中…' : `全部入库 (${items.length})`}
            </PillButton>
          </View>
        ) : null}
      </View>
    </View>
  )
}

export default RecognizeSheet
