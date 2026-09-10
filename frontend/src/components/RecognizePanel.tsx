/**
 * F5.1 拍照识别入库
 *
 * 拍照/选图 -> 视觉大模型 -> 候选清单 (逐条可改) -> 用户点「全部入库」才写库。
 * 刻意做成"草稿 + 确认": 识别一定会错, 让用户改比追求模型准确率划算。
 * 服务端没配视觉模型时返回 503, 这里降级成"手动添加", 不阻塞任何既有流程。
 */
import React, { useState } from 'react'
import { Alert, Modal, Upload, message } from 'antd'
import { CameraOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { PillButton } from './ui'
import { recognizeInventory } from '../api/inventory'
import { formatPercent } from '@shared/format'
import type { RecognitionItem, RecognitionResult } from '../types'

const UNIT_OPTIONS = ['个', '根', '颗', '块', '把', '条', '瓶', '袋', '盒', 'g', 'ml']

interface RecognizePanelProps {
  open: boolean
  onClose: () => void
  onConfirm: (items: RecognitionItem[]) => Promise<void> | void
}

const RecognizePanel: React.FC<RecognizePanelProps> = ({ open, onClose, onConfirm }) => {
  const [result, setResult] = useState<RecognitionResult | null>(null)
  const [items, setItems] = useState<RecognitionItem[]>([])
  const [busy, setBusy] = useState(false)
  const [degraded, setDegraded] = useState('')
  const [saving, setSaving] = useState(false)

  const reset = () => {
    setResult(null)
    setItems([])
    setDegraded('')
    setBusy(false)
  }

  const handleFile = async (file: File) => {
    setBusy(true)
    setDegraded('')
    try {
      const data = await recognizeInventory(file)
      setResult(data)
      setItems(data.items ?? [])
      if ((data.items ?? []).length === 0) {
        message.info('没认出食材, 换个角度再拍一张试试')
      }
    } catch (error) {
      setDegraded((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const patch = (index: number, next: Partial<RecognitionItem>) =>
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, ...next } : item)))

  const remove = (index: number) =>
    setItems((prev) => prev.filter((_, i) => i !== index))

  const addBlank = () =>
    setItems((prev) => [
      ...prev,
      { name: '', quantity: 1, unit: '个', category: '其他', confidence: null, expiry_days: null },
    ])

  const handleConfirm = async () => {
    const valid = items.filter((item) => item.name.trim() && item.quantity != null)
    if (valid.length === 0) {
      message.warning('至少填一样食材的名称和数量')
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

  const configured = !degraded.includes('配置视觉模型')

  return (
    <Modal
      title="拍照入库"
      open={open}
      onCancel={() => {
        reset()
        onClose()
      }}
      footer={null}
      width={520}
      destroyOnHidden
    >
      {!configured && (
        <Alert
          type="info"
          showIcon
          message="服务端还没配置视觉模型"
          description="可以先手动添加食材, 或者在 .env 里配好视觉模型后再用拍照。"
          style={{ marginBottom: 12 }}
        />
      )}
      {degraded && configured && (
        <Alert type="warning" showIcon message={degraded} style={{ marginBottom: 12 }} />
      )}

      <Upload.Dragger
        accept="image/*"
        capture={'environment' as never}
        showUploadList={false}
        disabled={busy}
        beforeUpload={(file) => {
          handleFile(file as unknown as File)
          return false
        }}
        style={{ borderRadius: 16 }}
      >
        <p style={{ margin: 0, fontSize: 28 }}>
          <CameraOutlined />
        </p>
        <p style={{ margin: '8px 0 2px', fontWeight: 600 }}>
          {busy ? '正在识别…' : items.length ? '换一张重新识别' : '拍一张冰箱 / 食材照片'}
        </p>
        <p className="field-hint" style={{ margin: 0 }}>
          识别出的只是草稿, 确认后才会入库
        </p>
      </Upload.Dragger>

      {result && (
        <div className="card-sub" style={{ marginTop: 10 }}>
          识别出 {items.length} 样
          {result.model ? ` · ${result.model}` : ''} · 今日已用 {result.used_today}/
          {result.daily_limit} 次
        </div>
      )}

      {items.length > 0 && (
        <div className="set-group" style={{ marginTop: 8 }}>
          {items.map((item, index) => (
            <div key={index} className="recog-row">
              <input
                className="text-input"
                value={item.name}
                placeholder="食材名称"
                onChange={(event) => patch(index, { name: event.target.value })}
              />
              <input
                className="text-input recog-qty"
                type="number"
                inputMode="decimal"
                value={item.quantity ?? ''}
                onChange={(event) =>
                  patch(index, {
                    quantity: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
              />
              <input
                className="text-input recog-unit"
                list="recog-units"
                value={item.unit}
                onChange={(event) => patch(index, { unit: event.target.value })}
              />
              <input
                className="text-input recog-expiry"
                type="number"
                inputMode="numeric"
                placeholder="天"
                value={item.expiry_days ?? ''}
                onChange={(event) =>
                  patch(index, {
                    expiry_days: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
              />
              <button type="button" className="card-link" onClick={() => remove(index)}>
                <DeleteOutlined />
              </button>
              {item.confidence != null && (
                <span className="recog-conf">置信 {formatPercent(item.confidence * 100)}</span>
              )}
            </div>
          ))}
          <datalist id="recog-units">
            {UNIT_OPTIONS.map((unit) => (
              <option key={unit} value={unit} />
            ))}
          </datalist>
        </div>
      )}

      <div className="stack-actions" style={{ marginTop: 16 }}>
        <PillButton variant="ghost" onClick={addBlank}>
          <PlusOutlined /> 手动加一行
        </PillButton>
        {items.length > 0 && (
          <PillButton block loading={saving} onClick={handleConfirm}>
            全部入库 ({items.length})
          </PillButton>
        )}
      </div>
    </Modal>
  )
}

export default RecognizePanel
