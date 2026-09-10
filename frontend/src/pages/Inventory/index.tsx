import React, { useCallback, useEffect, useState } from 'react'
import { DatePicker, Form, Input, Modal, Popconfirm, message } from 'antd'
import { CameraOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  Banner,
  Card,
  Chip,
  EmptyState,
  LoadingStack,
  PageHead,
  PillButton,
} from '../../components/ui'
import RecognizePanel from '../../components/RecognizePanel'
import { addInventoryItem, deleteInventoryItem, listInventory } from '../../api/inventory'
import { getToday } from '../../api/today'
import { formatAmount, formatRemaining } from '@shared/index'
import type { InventoryItem, RecognitionItem } from '../../types'

const UNIT_OPTIONS = ['个', '根', '颗', '块', '把', '条', '头', '瓶', 'g', 'ml']

const Inventory: React.FC = () => {
  const [items, setItems] = useState<InventoryItem[]>([])
  const [expiringCount, setExpiringCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [recognizeOpen, setRecognizeOpen] = useState(false)
  /** 今晚菜单用到的食材名 - 临期 banner 靠它判断"已排入今晚" */
  const [tonightNames, setTonightNames] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listInventory()
      setItems(result.items)
      setExpiringCount(result.expiring_count)
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setLoading(false)
    }
    try {
      const today = await getToday()
      setTonightNames((today.tonight?.ingredients ?? []).map((ing) => ing.name))
    } catch {
      setTonightNames([])
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await addInventoryItem({
        ingredient_name: values.ingredient_name.trim(),
        quantity: values.quantity,
        unit: values.unit,
        expiry_date: values.expiry_date ? values.expiry_date.format('YYYY-MM-DD') : null,
      })
      message.success('已入库')
      setOpen(false)
      form.resetFields()
      await load()
    } catch (err) {
      if (err instanceof Error) message.error(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleRecognized = async (items: RecognitionItem[]) => {
    let saved = 0
    for (const item of items) {
      if (!item.name || item.quantity == null) continue
      try {
        await addInventoryItem({
          ingredient_name: item.name,
          quantity: item.quantity,
          unit: item.unit || '个',
          expiry_date: item.expiry_days
            ? new Date(Date.now() + item.expiry_days * 86400000).toISOString().slice(0, 10)
            : null,
        })
        saved += 1
      } catch {
        // 单条失败不打断整体
      }
    }
    message.success(`已入库 ${saved} 样食材`)
    setRecognizeOpen(false)
    await load()
  }

  const handleDelete = async (item: InventoryItem) => {
    try {
      await deleteInventoryItem(item.id)
      message.success('已删除')
      await load()
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const visible = keyword.trim()
    ? items.filter((item) => item.ingredient_name.includes(keyword.trim()))
    : items

  const expiring = items.filter((item) => item.expiring_soon)
  const usedTonight = expiring.filter((item) => tonightNames.includes(item.ingredient_name))

  return (
    <div className="page">
      <PageHead
        title="冰箱"
        subtitle={
          items.length === 0
            ? '记下家里有什么, 采购清单会自动减去这些'
            : `${items.length} 样食材${expiringCount > 0 ? ` · ${expiringCount} 样快过期` : ' · 暂无临期'}`
        }
        extra={
          <div className="stack-actions is-row">
            <PillButton size="sm" variant="gray" onClick={() => setRecognizeOpen(true)}>
              <CameraOutlined /> 拍照
            </PillButton>
            <PillButton size="sm" onClick={() => setOpen(true)}>
              手动入库
            </PillButton>
          </div>
        }
      />

      <div className="page-footnote" style={{ marginTop: -6 }}>
        采购到货后会自动入库, 做饭标记已做会按菜谱自动扣减 —— 这里也能手动调整。
      </div>

      {expiring.length > 0 && (
        <Banner
          title={`${expiring.length} 样食材快过期`}
          text={
            usedTonight.length > 0
              ? `${usedTonight.map((item) => item.ingredient_name).join(' · ')} 已排入今晚菜单`
              : '优先排进这两天的菜单, 或者尽快吃掉'
          }
        />
      )}

      {loading ? (
        <LoadingStack rows={5} />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            title="冰箱还是空的"
            description="录入常备食材后, 采购清单会只列出真正缺的东西"
            actionLabel="录第一样食材"
            onAction={() => setOpen(true)}
          />
        </Card>
      ) : (
        <>
          <Input
            allowClear
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索食材"
          />
          <Card>
            <div className="set-group">
              {visible.map((item) => (
                <div key={item.id} className="inv-row">
                  <span
                    className={`inv-fresh ${
                      item.days_left != null && item.days_left <= 1
                        ? 'is-danger'
                        : item.expiring_soon
                          ? 'is-warn'
                          : ''
                    }`}
                  />
                  <div className="inv-main">
                    <div className="inv-name">
                      {item.ingredient_name}
                      {item.category && <Chip>{item.category}</Chip>}
                      {item.expiring_soon && <Chip tone="warn">{formatRemaining(item.days_left)}</Chip>}
                    </div>
                    <div className="inv-meta">
                      {item.expiry_date ? (
                        <span>{item.expiry_date} 到期</span>
                      ) : (
                        <span>未设置保质期</span>
                      )}
                    </div>
                  </div>
                  <div className="inv-qty">{formatAmount(item.quantity, item.unit)}</div>
                  <Popconfirm
                    title="删除这项库存?"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => handleDelete(item)}
                  >
                    <button type="button" className="card-link" aria-label="删除">
                      <DeleteOutlined />
                    </button>
                  </Popconfirm>
                </div>
              ))}
              {visible.length === 0 && (
                <div className="empty-hint" style={{ padding: '16px 0' }}>
                  没有匹配「{keyword}」的食材
                </div>
              )}
            </div>
          </Card>
        </>
      )}

      <div className="page-footnote">
        标记「做完了」时会按菜谱用量自动扣减这里的库存; 缺料不会阻断, 只会提醒你补。
      </div>

      <RecognizePanel
        open={recognizeOpen}
        onClose={() => setRecognizeOpen(false)}
        onConfirm={handleRecognized}
      />

      <Modal
        title="入库"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={handleSubmit}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" initialValues={{ unit: '个', quantity: 1 }}>
          <Form.Item
            name="ingredient_name"
            label="食材名称"
            rules={[{ required: true, message: '请输入食材名称' }]}
          >
            <Input placeholder="例如: 西红柿" />
          </Form.Item>
          <div className="field-grid">
            <Form.Item name="quantity" label="数量" rules={[{ required: true, message: '请输入数量' }]}>
              <Input type="number" min={0} />
            </Form.Item>
            <Form.Item name="unit" label="单位" rules={[{ required: true, message: '请选择单位' }]}>
              <Input list="unit-options" placeholder="个 / g / ml" />
            </Form.Item>
            <datalist id="unit-options">
              {UNIT_OPTIONS.map((unit) => (
                <option key={unit} value={unit} />
              ))}
            </datalist>
          </div>
          <Form.Item name="expiry_date" label="保质期 (可选)">
            <DatePicker
              style={{ width: '100%' }}
              disabledDate={(current) => current && current < dayjs().startOf('day')}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Inventory
