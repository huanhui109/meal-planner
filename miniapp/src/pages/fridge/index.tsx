/**
 * 冰箱库存 - Demo 结构: 页头(手动入库) + 工具行(搜索/补充常备) + 库存卡(fresh dot 行)
 *
 * 库存是"闭环"的入口: 采购清单算的是菜谱需求减库存, 标记已做又反过来扣库存,
 * 所以这里的数据质量直接决定那两处准不准。
 *
 * 接线 (2.7.0 新端点):
 *   - 搜索框 onInput → searchInventory(q) (GET /inventory?q=), 清空回退 listInventory
 *   - 补充常备食材 → bulkAddInventory (POST /inventory/bulk)
 *   - 点数量 → updateInventoryItem(itemId, { quantity }) (PUT /inventory/{id})
 *   - 点 × → deleteInventory(itemId)
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Input, Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh } from '@tarojs/taro'

import { formatQuantity } from '@shared/format'
import type { InventoryItem, RecognitionItem } from '@shared/types'

import { LoadingStack, PageHead } from '../../components/ui'
import {
  addInventory,
  bulkAddInventory,
  deleteInventory,
  listInventory,
  searchInventory,
  updateInventoryItem,
} from '../../lib/api'
import { RecognizeSheet } from '../../components/recognize-sheet'
import { ensureLogin, syncTabBar, toast } from '../../lib/nav'
import { useThemeClass } from '../../lib/theme'

/** 补充常备食材的固定三样 (Demo 同款) */
const STAPLES: Array<{ ingredient_name: string; quantity: number; unit: string }> = [
  { ingredient_name: '胡萝卜', quantity: 1, unit: '个' },
  { ingredient_name: '牛奶', quantity: 1, unit: '盒' },
  { ingredient_name: '黄瓜', quantity: 1, unit: '根' },
]

const SEARCH_DEBOUNCE_MS = 300

/** fresh dot: 没记保质期 = good; ≤1 天 danger; ≤2 天 warn; 其余 good */
function freshState(item: InventoryItem): 'good' | 'warn' | 'danger' {
  if (item.days_left == null) return 'good'
  if (item.days_left <= 1) return 'danger'
  if (item.days_left <= 2) return 'warn'
  return 'good'
}

function freshHint(item: InventoryItem): string {
  if (item.days_left == null) return '没记保质期'
  if (item.days_left <= 2) return `建议 ${Math.max(0, item.days_left)} 天内吃`
  return `还可放约 ${item.days_left} 天`
}

type EditableModalOption = Taro.showModal.Option & {
  editable?: boolean
  placeholderText?: string
}
type EditableModalResult = Taro.showModal.SuccessCallbackResult & { content?: string }

export default function FridgePage() {
  const themeClass = useThemeClass()
  const [items, setItems] = useState<InventoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [recognizeOpen, setRecognizeOpen] = useState(false)

  /** 入库 modal */
  const [modalOpen, setModalOpen] = useState(false)
  const [name, setName] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [unit, setUnit] = useState('个')
  const [saving, setSaving] = useState(false)
  const [filling, setFilling] = useState(false)

  /** 页面卸载后丢弃 setState, 避免 "setState on unmounted" 警告 */
  const aliveRef = useRef(true)
  useEffect(() => () => { aliveRef.current = false }, [])
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
  }, [])

  const load = useCallback(async () => {
    if (!ensureLogin()) return
    setError('')
    try {
      const result = await listInventory()
      if (!aliveRef.current) return
      setItems(result.items || [])
    } catch (err) {
      if (!aliveRef.current) return
      setError((err as Error).message)
    } finally {
      if (aliveRef.current) {
        setLoading(false)
        Taro.stopPullDownRefresh()
      }
    }
  }, [])

  useDidShow(() => {
    syncTabBar(3)
    void load()
  })

  usePullDownRefresh(() => {
    setQuery('')
    void load()
  })

  /** 搜索: 防抖后打 GET /inventory?q=; 清空时回退全量列表 */
  const handleSearchInput = (value: string) => {
    setQuery(value)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    const q = value.trim()
    searchTimer.current = setTimeout(async () => {
      if (!q) {
        void load()
        return
      }
      try {
        const result = await searchInventory(q)
        if (!aliveRef.current) return
        setItems(result.items || [])
      } catch (err) {
        if (aliveRef.current) toast((err as Error).message)
      }
    }, SEARCH_DEBOUNCE_MS)
  }

  const handleBulkFill = async () => {
    if (filling) return
    setFilling(true)
    try {
      const res = await bulkAddInventory(STAPLES)
      toast(`已补充 ${res.added?.length ?? STAPLES.length} 样常备食材`, 'success')
      setQuery('')
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setFilling(false)
    }
  }

  const handleAdd = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast('先写食材名称')
      return
    }
    const amount = Number(quantity)
    if (!quantity || Number.isNaN(amount) || amount <= 0) {
      toast('数量要填个大于 0 的数字')
      return
    }
    setSaving(true)
    try {
      await addInventory({
        ingredient_name: trimmed,
        quantity: amount,
        unit: unit.trim() || '个',
        source: 'manual',
      })
      toast(`${trimmed} 已加入冰箱`, 'success')
      setName('')
      setQuantity('1')
      setUnit('个')
      setModalOpen(false)
      setQuery('')
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  /** 点数量改数量 (PUT /inventory/{id}) */
  const handleEditQuantity = async (item: InventoryItem) => {
    const modal = (await Taro.showModal({
      title: `修改「${item.ingredient_name}」数量`,
      editable: true,
      placeholderText: `现在 ${formatQuantity(item.quantity)} ${item.unit}`,
      confirmText: '保存',
      cancelText: '取消',
    } as EditableModalOption)) as EditableModalResult
    if (!modal.confirm) return
    const next = Number((modal.content || '').trim())
    if (!Number.isFinite(next) || next <= 0) {
      toast('数量要填个大于 0 的数字')
      return
    }
    try {
      await updateInventoryItem(item.id, { quantity: next })
      toast('已更新数量', 'success')
      if (query.trim()) {
        handleSearchInput(query)
      } else {
        await load()
      }
    } catch (err) {
      toast((err as Error).message)
    }
  }

  const handleRemove = async (item: InventoryItem) => {
    try {
      await deleteInventory(item.id)
      setItems((prev) => prev.filter((x) => x.id !== item.id))
      toast(`已移除 ${item.ingredient_name}`)
    } catch (err) {
      toast((err as Error).message)
    }
  }

  const handleRecognized = async (recognized: RecognitionItem[]) => {
    let saved = 0
    for (const item of recognized) {
      if (!item.name || item.quantity == null) continue
      try {
        await addInventory({
          ingredient_name: item.name,
          quantity: item.quantity,
          unit: item.unit || '个',
          expiry_date: item.expiry_days
            ? new Date(Date.now() + item.expiry_days * 86400000).toISOString().slice(0, 10)
            : null,
          source: 'vision',
        })
        saved += 1
      } catch {
        // 单条失败不打断整体
      }
    }
    toast(`已入库 ${saved} 样食材`, 'success')
    setRecognizeOpen(false)
    setQuery('')
    await load()
  }

  const expiringCount = items.filter((item) => item.expiring_soon).length

  if (loading) {
    return (
      <View className={`page ${themeClass}`}>
        <PageHead title="冰箱" subtitle="正在数冰箱里的东西…" />
        <LoadingStack rows={4} />
      </View>
    )
  }

  return (
    <View className={`page ${themeClass}`}>
      <PageHead
        title="冰箱"
        subtitle={
          items.length === 0
            ? '还没有记过库存, 加几样试试'
            : `${items.length} 样食材 · ${expiringCount} 样建议优先吃`
        }
        action={
          <View className="d-btn d-btn--sm d-btn--primary tap" onClick={() => setModalOpen(true)}>
            <Text>手动入库</Text>
          </View>
        }
      />

      {error ? <View className="d-card d-card--tight" style={{ marginBottom: 12 }}><Text style={{ color: 'var(--red)', fontSize: 13 }}>{error}</Text></View> : null}

      {/* Demo tools: 搜索 + 补充常备食材 */}
      <View className="d-tools">
        <Input
          className="d-search"
          value={query}
          placeholder="搜索食材"
          onInput={(event) => handleSearchInput(event.detail.value)}
        />
        <View className={`d-btn tap${filling ? ' d-btn--disabled' : ''}`} onClick={() => void handleBulkFill()}>
          <Text>{filling ? '补充中…' : '补充常备食材'}</Text>
        </View>
      </View>
      <View className="d-quick-note" style={{ margin: '8px 4px 0' }}>
        <Text onClick={() => setRecognizeOpen(true)}>拍照入库 →</Text>
      </View>

      {/* Demo 库存卡: fresh dot + 名称 + 数量(点按可改) + 移除 */}
      <View className="d-card" style={{ marginTop: 12 }}>
        {items.length === 0 ? (
          <View className="d-empty-state">
            {query.trim() ? '没有匹配的食材' : '冰箱是空的，买菜回来顺手记一笔'}
          </View>
        ) : (
          items.map((item) => {
            const state = freshState(item)
            return (
              <View key={item.id} className="d-inv-row">
                <View className={`d-fresh${state === 'warn' ? ' d-fresh--warn' : state === 'danger' ? ' d-fresh--danger' : ''}`} />
                <View className="d-inv-name">
                  <Text className="d-inv-name__name">{item.ingredient_name}</Text>
                  <View className="d-inv-name__sub">{freshHint(item)}</View>
                </View>
                <Text className="d-inv-qty tap" onClick={() => void handleEditQuantity(item)}>
                  {formatQuantity(item.quantity)} {item.unit}
                </Text>
                <View className="d-icon-btn tap" onClick={() => void handleRemove(item)}>
                  <Text>×</Text>
                </View>
              </View>
            )
          })
        )}
      </View>

      {/* Demo 入库 modal */}
      {modalOpen ? (
        <View className="d-modal-overlay" onClick={() => setModalOpen(false)}>
          <View className="d-modal" onClick={(e) => e.stopPropagation()}>
            <Text className="d-modal__title">入库一样食材</Text>
            <View className="d-field">
              <View className="d-field__label">食材名称</View>
              <Input
                className="d-field__input"
                value={name}
                placeholder="例如：西红柿"
                onInput={(event) => setName(event.detail.value)}
              />
            </View>
            <View className="d-field-row">
              <View className="d-field">
                <View className="d-field__label">数量</View>
                <Input
                  className="d-field__input"
                  type="digit"
                  value={quantity}
                  onInput={(event) => setQuantity(event.detail.value)}
                />
              </View>
              <View className="d-field">
                <View className="d-field__label">单位</View>
                <Input
                  className="d-field__input"
                  value={unit}
                  onInput={(event) => setUnit(event.detail.value)}
                />
              </View>
            </View>
            <View className="d-modal-actions">
              <View className="d-btn tap" onClick={() => setModalOpen(false)}>
                <Text>取消</Text>
              </View>
              <View className={`d-btn d-btn--primary tap${saving ? ' d-btn--disabled' : ''}`} onClick={() => void handleAdd()}>
                <Text>{saving ? '入库中…' : '加入冰箱'}</Text>
              </View>
            </View>
          </View>
        </View>
      ) : null}

      <RecognizeSheet
        open={recognizeOpen}
        onClose={() => setRecognizeOpen(false)}
        onConfirm={handleRecognized}
      />

      <View style={{ height: 24 }} />
    </View>
  )
}
