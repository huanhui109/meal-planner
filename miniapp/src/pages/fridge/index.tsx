/**
 * 冰箱库存 - 列表 + 入库 + 临期高亮
 *
 * 库存是"闭环"的入口: 采购清单算的是菜谱需求减库存, 标记已做又反过来扣库存,
 * 所以这里的数据质量直接决定那两处准不准。
 */
import { useCallback, useMemo, useState } from 'react'
import { Input, Picker, ScrollView, Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh } from '@tarojs/taro'

import { formatExpiry, formatQuantity, todayIso } from '@shared/format'
import type { InventoryItem, RecognitionItem } from '@shared/types'

import {
  Banner,
  Card,
  LoadingStack,
  PageHead,
  PillButton,
  SectionTitle,
} from '../../components/ui'
import { addInventory, getToday, listInventory } from '../../lib/api'
import { RecognizeSheet } from '../../components/recognize-sheet'
import { ensureLogin, syncTabBar, toast } from '../../lib/nav'
import { px } from '../../lib/px'

const UNITS = ['g', 'kg', 'ml', 'L', '个', '根', '颗', '把', '袋', '盒']

export default function FridgePage() {
  const [items, setItems] = useState<InventoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [active, setActive] = useState<'all' | 'expiring'>('all')
  const [recognizeOpen, setRecognizeOpen] = useState(false)
  /** 今晚菜单用到的食材名 - 临期 banner 靠它判断"已排入今晚" */
  const [tonightNames, setTonightNames] = useState<string[]>([])

  const [name, setName] = useState('')
  const [quantity, setQuantity] = useState('')
  const [unitIndex, setUnitIndex] = useState(0)
  const [expiry, setExpiry] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    if (!ensureLogin()) return
    setError('')
    try {
      setItems((await listInventory()) || [])
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
      Taro.stopPullDownRefresh()
    }
    try {
      const today = await getToday()
      setTonightNames((today.tonight?.ingredients ?? []).map((ing) => ing.name))
    } catch {
      setTonightNames([])
    }
  }, [])

  useDidShow(() => {
    syncTabBar(3)
    void load()
  })

  usePullDownRefresh(() => {
    void load()
  })

  const expiring = useMemo(() => items.filter((item) => item.expiring_soon), [items])
  const usedTonight = expiring.filter((item) => tonightNames.includes(item.ingredient_name))
  const shown = active === 'expiring' ? expiring : items

  const handleAdd = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast('先写食材名字')
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
        unit: UNITS[unitIndex],
        expiry_date: expiry || undefined,
        source: 'manual',
      })
      toast('已入库', 'success')
      setName('')
      setQuantity('')
      setExpiry('')
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setSaving(false)
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
    await load()
  }

  if (loading) {
    return (
      <View className="page">
        <PageHead title="冰箱" subtitle="正在数冰箱里的东西…" />
        <LoadingStack rows={4} />
      </View>
    )
  }

  return (
    <View className="page">
      <PageHead
        title="冰箱"
        subtitle={
          items.length === 0
            ? '还没有记过库存, 加几样试试'
            : `共 ${items.length} 样${expiring.length ? `, ${expiring.length} 样快过期` : ''}`
        }
      />

      {error ? <Banner tone="danger">{error}</Banner> : null}

      {expiring.length > 0 ? (
        <Banner tone="warn">
          有 {expiring.length} 样快过期了
          {usedTonight.length > 0
            ? `, ${usedTonight.map((item) => item.ingredient_name).join('、')} 已排入今晚菜单。`
            : ', 优先用掉它们能省不少钱。'}
        </Banner>
      ) : null}

      <Card>
        <View className="card__head">
          <Text className="card__label">拍照入库</Text>
          <Text className="card__hint" style={{ marginTop: 0 }}>
            拍一张就知道大概有什么
          </Text>
        </View>
        <PillButton block variant="gray" onClick={() => setRecognizeOpen(true)}>
          拍照识别
        </PillButton>
        <View className="card__hint">
          识别结果只是草稿, 确认后才会入库; 采购到货自动入库, 做饭也会自动扣减。
        </View>
      </Card>

      <Card>
        <View className="card__head">
          <Text className="card__label">记一笔入库</Text>
          <Text className="card__hint" style={{ marginTop: 0 }}>
            冰箱有数了, 采购清单才准
          </Text>
        </View>

        <View className="field">
          <View className="field__label">食材</View>
          <Input
            className="text-input"
            value={name}
            placeholder="比如 西红柿"
            onInput={(event) => setName(event.detail.value)}
          />
        </View>

        <View style={{ display: 'flex', gap: px(10) }}>
          <View className="field" style={{ flex: 1 }}>
            <View className="field__label">数量</View>
            <Input
              className="text-input"
              type="digit"
              value={quantity}
              placeholder="500"
              onInput={(event) => setQuantity(event.detail.value)}
            />
          </View>
          <View className="field" style={{ width: 100 }}>
            <View className="field__label">单位</View>
            <Picker
              mode="selector"
              range={UNITS}
              value={unitIndex}
              onChange={(event) => setUnitIndex(Number(event.detail.value))}
            >
              <View className="text-input" style={{ display: 'flex', alignItems: 'center' }}>
                {UNITS[unitIndex]}
              </View>
            </Picker>
          </View>
        </View>

        <View className="field">
          <View className="field__label">保质期 (可不填)</View>
          <Picker
            mode="date"
            start="2024-01-01"
            value={expiry || todayIso()}
            onChange={(event) => setExpiry(String(event.detail.value))}
          >
            <View className="text-input" style={{ display: 'flex', alignItems: 'center' }}>
              {expiry || '选择日期'}
            </View>
          </Picker>
        </View>

        <View style={{ marginTop: 18 }}>
          <PillButton block disabled={saving} onClick={handleAdd}>
            {saving ? '入库中…' : '加进冰箱'}
          </PillButton>
        </View>
      </Card>

      <SectionTitle text="冰箱里" hint={`${items.length} 样`} />

      <View style={{ display: 'flex', gap: px(8), marginBottom: px(10) }}>
        <View
          className={`chip-option tap${active === 'all' ? ' chip-option--on' : ''}`}
          onClick={() => setActive('all')}
        >
          全部
        </View>
        <View
          className={`chip-option tap${active === 'expiring' ? ' chip-option--on' : ''}`}
          onClick={() => setActive('expiring')}
        >
          快过期 {expiring.length}
        </View>
      </View>

      {shown.length === 0 ? (
        <Card>
          <Text className="empty__title">{active === 'expiring' ? '没有临期食材' : '冰箱是空的'}</Text>
          <View className="empty__desc">
            {active === 'expiring'
              ? '挺好, 说明没囤太多东西。'
              : '买菜回来顺手记一笔, 之后采购清单会自动扣掉这些量。'}
          </View>
        </Card>
      ) : (
        <Card tight>
          {shown.map((item) => (
            <View
              key={item.id}
              className={`inv-row${item.expiring_soon ? ' inv-row--expiring' : ''}`}
            >
              <View style={{ flex: 1 }}>
                <Text className="inv-row__name">{item.ingredient_name}</Text>
                <View className="inv-row__meta">
                  {[item.category, item.expiry_date ? formatExpiry(item.days_left) : null]
                    .filter(Boolean)
                    .join(' · ')}
                </View>
              </View>
              <Text className="inv-row__qty">
                {formatQuantity(item.quantity)}
                {item.unit}
              </Text>
            </View>
          ))}
        </Card>
      )}

      <RecognizeSheet
        open={recognizeOpen}
        onClose={() => setRecognizeOpen(false)}
        onConfirm={handleRecognized}
      />

      <View style={{ height: 24 }} />
    </View>
  )
}
