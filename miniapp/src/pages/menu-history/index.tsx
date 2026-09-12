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

interface HistoryItem {
  id: number
  week_start_date: string | null
  status: string
  is_confirmed: boolean
  totals: Record<string, unknown>
}

const WEEK_OPTIONS = [4, 8, 12]

export default function MenuHistoryPage() {
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

  const handleReuse = (item: HistoryItem) => {
    // 复用: 把这份菜单的 id 带回去, 让新菜单生成时参考它的锁定项
    Taro.showModal({
      title: '复用这份菜单',
      content: `会用 ${item.week_start_date || '这份'}的锁定项作为参考, 重新生成一份新菜单`,
      confirmText: '去生成',
      cancelText: '再看看',
    }).then((res) => {
      if (!res.confirm) return
      Taro.navigateTo({ url: `/pages/menu/index?reuse_from=${item.id}` })
    })
  }

  return (
    <View className="page">
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
              一键复用
            </PillButton>
          </View>
        </Card>
      ))}

      <View style={{ height: 24 }} />
    </View>
  )
}
