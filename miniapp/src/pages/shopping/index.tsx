/**
 * 采购清单 - 冰箱已有 vs 需要买
 *
 * 后端已经把"菜谱需求量 - 冰箱库存量"的差集算好了, 这里只负责按品类分组展示
 * 与一键复制 (复制成纯文本, 直接粘到买菜 App 或发给家人)。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh } from '@tarojs/taro'

import { formatAmount, formatDateRange, formatMoney, formatMonthDay, weekEnd } from '@shared/format'
import { categoryRank } from '@shared/labels'
import { orderStatusText, orderSummaryText } from '@shared/today'
import type { MenuDetail, OrderSuggestion, ShoppingItem, ShoppingList } from '@shared/types'

import { Banner, Card, LoadingStack, PageHead, PillButton, SectionTitle } from '../../components/ui'
import { getCurrentMenu, getOrderSuggestion, getShoppingList, searchProducts } from '../../lib/api'
import { openPurchaseLink, missingText } from '../../lib/deeplink'
import { ensureLogin, goTo, syncTabBar, toast } from '../../lib/nav'

interface Group {
  category: string
  items: ShoppingItem[]
}

export default function ShoppingPage() {
  const [menu, setMenu] = useState<MenuDetail | null>(null)
  const [list, setList] = useState<ShoppingList | null>(null)
  const [checked, setChecked] = useState<Record<number, boolean>>({})
  const [order, setOrder] = useState<OrderSuggestion | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /** 页面卸载后丢弃 setState, 避免 "setState on unmounted" 警告 */
  const aliveRef = useRef(true)
  useEffect(() => () => { aliveRef.current = false }, [])

  const load = useCallback(async () => {
    if (!ensureLogin()) return
    setError('')
    try {
      const current = await getCurrentMenu()
      if (!aliveRef.current) return
      setMenu(current)
      setList(current?.id ? await getShoppingList(current.id) : null)
      try {
        const next = current?.id ? await getOrderSuggestion(current.id) : null
        if (!aliveRef.current) return
        setOrder(next)
      } catch {
        if (aliveRef.current) setOrder(null)
      }
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
    syncTabBar(2)
    void load()
  })

  usePullDownRefresh(() => {
    void load()
  })

  const toBuy = useMemo(() => (list?.items || []).filter((item) => !item.have_enough), [list])

  const groups: Group[] = useMemo(() => {
    const map = new Map<string, ShoppingItem[]>()
    for (const item of toBuy) {
      const key = item.category || '其他'
      map.set(key, [...(map.get(key) || []), item])
    }
    return Array.from(map.entries())
      .map(([category, items]) => ({ category, items }))
      .sort((a, b) => categoryRank(a.category) - categoryRank(b.category))
  }, [toBuy])

  /** V3.0 实价查询: 后端 scraper 全是 stub, 命中不到数据时显式说明"即将上线" */
  const checkRealPrice = async (name: string) => {
    try {
      const res = await searchProducts(name)
      if (res.total === 0) {
        Taro.showToast({ title: res.v3_status || '实价查询 V3.0 即将上线', icon: 'none' })
        return
      }
      Taro.showModal({
        title: `${name} · 实时报价`,
        content: res.items
          .slice(0, 5)
          .map((p) => `${p.name} — ¥${p.price}${p.unit ? '/' + p.unit : ''} (${p.platform})`)
          .join('\n'),
        showCancel: false,
      })
    } catch {
      Taro.showToast({ title: '暂时查不到, 稍后再试', icon: 'none' })
    }
  }

  const copyList = async () => {
    if (!menu || groups.length === 0) {
      toast('没有要买的东西')
      return
    }
    const lines = [
      `买菜清单 (${formatDateRange(menu.week_start_date, weekEnd(menu.week_start_date))})`,
      '',
    ]
    for (const group of groups) {
      lines.push(`【${group.category}】`)
      for (const item of group.items) {
        lines.push(`· ${item.name} ${formatAmount(item.deficit, item.unit)}`)
      }
      lines.push('')
    }
    await Taro.setClipboardData({ data: lines.join('\n') })
    toast('清单已复制', 'success')
  }

  if (loading) {
    return (
      <View className="page">
        <PageHead title="采购清单" subtitle="正在对比菜谱和冰箱…" />
        <LoadingStack rows={4} />
      </View>
    )
  }

  if (!menu || !list) {
    return (
      <View className="page">
        <PageHead title="采购清单" subtitle="有菜单之后才有清单" />
        {error ? <Banner tone="danger">{error}</Banner> : null}
        <Card>
          <Text className="empty__title">还没有清单</Text>
          <View className="empty__desc">先生成这周的菜单, 系统会按菜谱算出要买什么。</View>
          <PillButton block onClick={() => goTo('/menus')}>
            去生成菜单
          </PillButton>
        </Card>
      </View>
    )
  }

  const total = list.summary.total_count
  const have = list.summary.have_count

  return (
    <View className="page">
      <PageHead
        title="采购清单"
        subtitle={`${formatMonthDay(list.week_start_date)} 那周 · 共 ${total} 样, 冰箱已有 ${have} 样`}
      />

      {error ? <Banner tone="danger">{error}</Banner> : null}

      {order ? (
        <Card>
          <View className="card__head">
            <Text className="card__label">一键补单</Text>
            <Text className={`chip chip--${order.reaches_min_order ? 'accent' : 'warn'}`}>
              {orderStatusText(order)}
            </Text>
          </View>
          <View className="card__hint">{orderSummaryText(order)}</View>
          {order.note ? <View className="card__hint">{order.note}</View> : null}
          <View style={{ marginTop: 12 }}>
            <PillButton
              block
              onClick={() =>
                openPurchaseLink({
                  miniappAppId: order.miniapp_app_id,
                  link: order.order_link,
                  copyText: missingText(order.items),
                })
              }
            >
              去小象超市下单
            </PillButton>
          </View>
        </Card>
      ) : null}

      {list.summary.unit_mismatch_count > 0 ? (
        <Banner tone="warn">
          有 {list.summary.unit_mismatch_count} 样单位对不上 (比如菜谱写"2个"、冰箱记的是克), 建议按实际用量买。
        </Banner>
      ) : null}

      <Card>
        <View className="card__head">
          <Text className="card__label">需要买</Text>
          <Text className="chip chip--ink">{toBuy.length} 样</Text>
        </View>
        <View className="card__hint">
          {toBuy.length === 0 ? '冰箱里的量已经够了, 不用买。' : '点名字可以划掉买到的。'}
        </View>
        <View style={{ marginTop: 12 }}>
          <PillButton block onClick={copyList} disabled={toBuy.length === 0}>
            一键复制清单
          </PillButton>
        </View>
      </Card>

      {groups.map((group) => (
        <View key={group.category} className="shop-group">
          <View className="shop-group__title">{group.category}</View>
          <Card tight>
            {group.items.map((item) => {
              const on = checked[item.ingredient_id]
              return (
                <View
                  key={item.ingredient_id}
                  className={`shop-row tap${on ? ' shop-row--done' : ''}`}
                  onClick={() =>
                    setChecked((prev) => ({ ...prev, [item.ingredient_id]: !prev[item.ingredient_id] }))
                  }
                >
                  <View className={`shop-check${on ? ' shop-check--on' : ''}`} />
                  <View style={{ flex: 1 }}>
                    <Text className="shop-row__name">{item.name}</Text>
                  </View>
                  <Text className="shop-row__qty">
                    {item.quantitative ? formatAmount(item.deficit, item.unit) : '按需'}
                  </Text>
                  <Text
                    className="shop-row__price"
                    onClick={(e) => {
                      e.stopPropagation()
                      void checkRealPrice(item.name)
                    }}
                  >
                    查实价
                  </Text>
                </View>
              )
            })}
          </Card>
        </View>
      ))}

      {toBuy.length > 0 ? null : (
        <>
          <SectionTitle text="冰箱已有" hint={`${have} 样`} />
          <Card tight>
            {list.items
              .filter((item) => item.have_enough)
              .map((item) => (
                <View key={item.ingredient_id} className="shop-row">
                  <View className="shop-check shop-check--on" />
                  <View style={{ flex: 1 }}>
                    <Text className="shop-row__name">{item.name}</Text>
                  </View>
                  <Text className="shop-row__qty">
                    {formatAmount(item.in_stock_quantity, item.unit)}
                  </Text>
                </View>
              ))}
          </Card>
        </>
      )}

      <View style={{ height: 24 }} />
    </View>
  )
}
