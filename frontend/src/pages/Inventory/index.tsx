import React, { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Skeleton,
  Space,
  Tag,
  message,
} from 'antd'
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import PageHeader from '../../components/PageHeader'
import { addInventoryItem, deleteInventoryItem, listInventory } from '../../api/inventory'
import type { InventoryItem } from '../../types'

const UNIT_OPTIONS = ['个', '根', '颗', '块', '把', '条', '头', '瓶', 'g', 'ml']

const Inventory: React.FC = () => {
  const [items, setItems] = useState<InventoryItem[]>([])
  const [expiringCount, setExpiringCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
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

  const handleDelete = async (item: InventoryItem) => {
    try {
      await deleteInventoryItem(item.id)
      message.success('已删除')
      await load()
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="冰箱库存"
        subtitle={expiringCount > 0 ? `${items.length} 项 · ${expiringCount} 项临期` : `${items.length} 项`}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
              入库
            </Button>
          </Space>
        }
      />

      {expiringCount > 0 && (
        <Alert
          type="warning"
          showIcon
          className="page-alert"
          message={`有 ${expiringCount} 项食材 3 天内到期, 建议优先安排到菜单里`}
        />
      )}

      {loading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : items.length === 0 ? (
        <div className="card">
          <Empty description="库存还是空的, 先录入一些食材吧">
            <Button type="primary" onClick={() => setOpen(true)}>
              入库
            </Button>
          </Empty>
        </div>
      ) : (
        <div className="card">
          <ul className="inventory-list">
            {items.map((item) => (
              <li key={item.id} className={item.expiring_soon ? 'is-expiring' : ''}>
                <div className="inventory-main">
                  <div className="inventory-name">
                    {item.ingredient_name}
                    {item.category && <Tag className="tag-soft">{item.category}</Tag>}
                    {item.expiring_soon && <Tag color="orange">临期</Tag>}
                  </div>
                  <div className="inventory-meta">
                    <span className="inventory-qty">
                      {Number(item.quantity.toFixed(2))}
                      {item.unit}
                    </span>
                    {item.expiry_date ? (
                      <span>
                        {item.expiry_date} 到期
                        {item.days_left != null && item.days_left >= 0 ? ` (剩 ${item.days_left} 天)` : ' (已过期)'}
                      </span>
                    ) : (
                      <span>未设置保质期</span>
                    )}
                  </div>
                </div>
                <Popconfirm
                  title="删除这项库存?"
                  okText="删除"
                  cancelText="取消"
                  onConfirm={() => handleDelete(item)}
                >
                  <Button type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Modal
        title="入库"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={handleSubmit}
        confirmLoading={saving}
        okText="保存"
      >
        <Form form={form} layout="vertical" initialValues={{ unit: '个' }}>
          <Form.Item
            name="ingredient_name"
            label="食材名称"
            rules={[{ required: true, message: '请输入食材名称' }]}
          >
            <Input placeholder="例如: 西红柿" />
          </Form.Item>
          <Space size="large" style={{ width: '100%' }}>
            <Form.Item name="quantity" label="数量" rules={[{ required: true, message: '请输入数量' }]}>
              <InputNumber min={0.01} step={1} style={{ width: 140 }} placeholder="2" />
            </Form.Item>
            <Form.Item name="unit" label="单位" rules={[{ required: true }]}>
              <Input style={{ width: 120 }} placeholder="个" />
            </Form.Item>
          </Space>
          <div className="form-hint">单位建议使用: {UNIT_OPTIONS.join(' / ')}</div>
          <Form.Item name="expiry_date" label="保质期 (可选)">
            <DatePicker style={{ width: '100%' }} disabledDate={(current) => current.isBefore(dayjs().startOf('day'))} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Inventory
