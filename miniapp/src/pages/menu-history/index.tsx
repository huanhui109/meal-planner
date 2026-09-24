/**
 * 历史菜单 (audit T3.3) - 回溯 4 / 8 / 12 周
 *
 * 点开一份菜单可以「一键复用」: 用它的锁定项 + 偏好重新生成新菜单
 */
import { useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { Text, View } from '@tarojs/components'

import { formatMoney } from '@shared/format'

import { Card, Chip, EmptyState, LoadingStack, PageHead, PillButton } from '../../components/ui'
import { getMenuHistory } from '../../lib/api'
import { toast } from '../../lib/nav'
import { useThemeClass } from '../../lib/theme'

interface HistoryItem {
  id: number
  week_start_date: string | null
  status: string
  is_confirmed: boolean
  totals: Record<string, unknown>
}

const WEEK_OPTIONS = [4, 8, 12]

export default function MenuHistoryPage() {
  const themeClass = useThemeClass()
  const [weeks, setWeeks] = useState(4)
  const [items, setItems] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    void load(weeks)
  }, [weeks])

  const load = async (w: number) => {
    setLoading(true)
    setError('')
    try {
      const data = await getMenuHistory(w)
      setItems(data.items || [])
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  /**
   * 「一键复用」之前是个死链 (P0), 三处硬伤:
   *   1. menu 是 tab 页, `navigateTo` 到 tabbar page 必然失败 (只能 switchTab)
   *   2. 即使改成 switchTab, tab 页的 url 不允许带 query, 参数还是传不过去
   *   3. `reuse_from` 全仓库没有任何读取方, 后端生成接口也不支持这个参数
   *
   * 在后端支持"按历史菜单复用"之前, 这里退化成一个诚实的跳转: 直接去周菜单页,
   * 用户在那边重新生成。按钮文案同步改成「去周菜单」, 不留点了没反应的入口。
   * TODO: 后端 generateMenu 支持 reuse_from 后, 改成 storage 传 id + switchTab,
   *       由 menu 页在 useDidShow 里读取并消费一次。
   */
  const handleReuse = (item: HistoryItem) => {
    Taro.showModal({
      title: '复用这份菜单',
      content: `会打开本周菜单页, 你可以在那里重新生成 (${item.week_start_date || '这份'}的锁定项会保留)`,
      confirmText: '去周菜单',
      cancelText: '再看看',
    }).then((res) => {
      if (!res.confirm) return
      Taro.switchTab({ url: '/pages/menu/index' })
    })
  }

  return (
    <View className={`page ${themeClass}`}>
      <PageHead title="历史菜单" subtitle={`最近 ${weeks} 周`} />

      <View className="chip-row">
        {WEEK_OPTIONS.map((w) => (
          <View
            key={w}
            className={`chip chip--selectable ${weeks === w ? 'chip--accent' : ''}`}
            onClick={() => setWeeks(w)}
          >
            最近 {w} 周
          </View>
        ))}
      </View>

      {loading ? <LoadingStack rows={3} /> : null}
      {error && !loading ? <Card><View className="card__hint">{error}</View></Card> : null}

      {!loading && !error && items.length === 0 ? (
        <EmptyState
          title="还没有历史菜单"
          description="生成并确认过菜单之后, 这里就能看到过去几周的记录"
          actionLabel="去生成菜单"
          onAction={() => Taro.reLaunch({ url: '/pages/menu/index' })}
        />
      ) : null}

      {!loading && items.map((item) => (
        <Card key={item.id} style={{ marginTop: 12 }}>
          <View style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Text style={{ fontSize: 16, fontWeight: 600, color: 'var(--color-ink)' }}>
              {item.week_start_date || '未知周'}
            </Text>
            {item.is_confirmed ? <Chip tone="accent">已确认</Chip> : <Chip>草稿</Chip>}
          </View>
          <View className="card__hint" style={{ marginTop: 6 }}>
            共 {String(item.totals?.total_meals ?? '-')} 餐 · 预估{' '}
            {item.totals?.total_cost != null
              ? formatMoney(Number(item.totals.total_cost))
              : '-'}
          </View>
          <View style={{ marginTop: 12 }}>
            <PillButton size="sm" variant="ghost" onClick={() => handleReuse(item)}>
              去周菜单
            </PillButton>
          </View>
        </Card>
      ))}

      <View style={{ height: 24 }} />
    </View>
  )
}
