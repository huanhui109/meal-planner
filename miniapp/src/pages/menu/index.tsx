/**
 * 周菜单 - 星期条 + 当天全部餐次
 *
 * 交互: 换一道 / 锁定(重生成时保留) / 标记已做(扣库存)。
 * 草稿状态顶部会有"确认菜单"的引导, 确认后采购清单才作数。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ScrollView, Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh } from '@tarojs/taro'

import {
  currentWeekStart,
  formatDateRange,
  formatMoney,
  formatMonthDay,
  formatProgress,
  todayIso,
  weekEnd,
} from '@shared/format'
import { MEAL_ORDER, mealLabel, weekdayLabel } from '@shared/labels'
import type { MenuDay, MenuDetail } from '@shared/types'

import {
  Bar,
  Banner,
  Card,
  LoadingStack,
  PageHead,
  PillButton,
} from '../../components/ui'
import { confirmMenu, getCurrentMenu } from '../../lib/api'
import { ensureLogin, goTo, syncTabBar, toast } from '../../lib/nav'
import { px } from '../../lib/px'
import { askReplaceRecipe, markCooked, toggleLock } from '../../lib/meal-actions'
import { startGeneration, waitForGeneration } from '../../lib/menu'

export default function MenuPage() {
  const [menu, setMenu] = useState<MenuDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(todayIso())

  const load = useCallback(async () => {
    if (!ensureLogin()) return
    setError('')
    try {
      const data = await getCurrentMenu()
      setMenu(data)
      if (data && !data.days.some((day) => day.date === selected)) {
        setSelected(data.days[0]?.date ?? selected)
      }
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
      Taro.stopPullDownRefresh()
    }
  }, [selected])

  useDidShow(() => {
    syncTabBar(1)
    void load()
  })

  useEffect(() => {
    if (!loading) Taro.stopPullDownRefresh()
  }, [loading])

  usePullDownRefresh(() => {
    void load()
  })

  const day: MenuDay | undefined = useMemo(
    () => menu?.days.find((item) => item.date === selected),
    [menu, selected],
  )

  const handleGenerate = async (force = false) => {
    setBusy(true)
    try {
      const accepted = await startGeneration(currentWeekStart(), force)
      if (accepted.reused && accepted.menu_id) {
        toast('已经有一份这周的菜单了')
        await load()
        return
      }
      if (accepted.task_id) {
        const task = await waitForGeneration(accepted.task_id)
        if (task.status === 'failed') toast(task.error || '生成失败')
        else toast('生成好了', 'success')
      }
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleConfirm = async () => {
    if (!menu) return
    setBusy(true)
    try {
      await confirmMenu(menu.id)
      toast('菜单已确认', 'success')
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleReplace = async (itemId: number, name: string) => {
    if (!menu) return
    try {
      const changed = await askReplaceRecipe(menu, itemId, name)
      if (changed) await load()
    } catch (err) {
      toast((err as Error).message)
    }
  }

  const handleLock = async (itemId: number, locked: boolean) => {
    if (!menu) return
    try {
      await toggleLock(menu, itemId, locked)
      await load()
    } catch (err) {
      toast((err as Error).message)
    }
  }

  const handleCook = async (itemId: number) => {
    if (!menu) return
    try {
      const changed = await markCooked(menu, itemId)
      if (changed) await load()
    } catch (err) {
      toast((err as Error).message)
    }
  }

  if (loading) {
    return (
      <View className="page">
        <PageHead title="周菜单" subtitle="正在读取本周安排…" />
        <LoadingStack rows={4} />
      </View>
    )
  }

  if (!menu) {
    return (
      <View className="page">
        <PageHead title="周菜单" subtitle="还没有菜单, 先生成一份" />
        {error ? <Banner tone="danger">{error}</Banner> : null}
        <Card>
          <Text className="empty__title">这周还没有菜单</Text>
          <View className="empty__desc">
            AI 会按你的偏好排好 7 天, 并算好营养与预算。生成大约要 1-2 分钟。
          </View>
          <PillButton block disabled={busy} onClick={() => handleGenerate(false)}>
            {busy ? 'AI 正在生成…' : '生成菜单'}
          </PillButton>
        </Card>
      </View>
    )
  }

  return (
    <View className="page">
      <PageHead
        title="周菜单"
        subtitle={`${formatDateRange(menu.week_start_date, weekEnd(menu.week_start_date))} · ${formatProgress(menu.totals.cooked_count, menu.totals.meal_count)} 已做`}
      />

      {error ? <Banner tone="danger">{error}</Banner> : null}

      <Card>
        <View className="card__head">
          <Text className="card__label">这周总览</Text>
          <Text className="chip">{menu.status === 'draft' ? '待确认' : '已确认'}</Text>
        </View>
        <View className="card__hint">
          由 AI {menu.created_at ? `${menu.created_at.replace('T', ' ').slice(5, 16)} 生成` : '生成'}
          {' · '}预估 {formatMoney(menu.totals.estimated_cost)}
        </View>
        <View style={{ marginTop: 10 }}>
          <Bar
            value={
              menu.budget.budget_limit > 0
                ? (menu.budget.total_estimated / menu.budget.budget_limit) * 100
                : 0
            }
            tone={menu.budget.passed ? 'accent' : 'warn'}
          />
        </View>
        <View className="card__hint">
          {menu.budget.passed
            ? `预算内, 还剩 ${formatMoney(Math.max(0, menu.budget.budget_limit - menu.budget.total_estimated))}`
            : `超出 ${formatMoney(menu.budget.over_amount)}, 换掉一两道贵的菜就能压回来`}
          {' · '}
          {menu.nutrition.passed
            ? `周均 ${Math.round(menu.nutrition.weekly_avg_calories)} kcal 达标`
            : menu.nutrition.issues[0] || '营养有偏离'}
        </View>
        <View style={{ marginTop: 12 }}>
          <PillButton variant="gray" block disabled={busy} onClick={() => handleGenerate(true)}>
            {busy ? '处理中…' : '重新生成 (锁定的餐次原样保留)'}
          </PillButton>
        </View>
      </Card>

      {menu.status === 'draft' ? (
        <Card>
          <View className="card__head">
            <View>
              <Text className="card__label">这份菜单还是草稿</Text>
              <View className="card__hint">
                可以先换掉不想吃的菜, 确认后锁定, 采购清单才作数。
              </View>
            </View>
          </View>
          <View style={{ marginTop: 14 }}>
            <PillButton block disabled={busy} onClick={handleConfirm}>
              {busy ? '处理中…' : '确认这周的菜单'}
            </PillButton>
          </View>
        </Card>
      ) : null}

      <ScrollView scrollX className="day-strip">
        <View className="day-strip__inner">
          {menu.days.map((item, index) => (
            <View
              key={item.date}
              className={`day-pill tap${item.date === selected ? ' day-pill--active' : ''}`}
              onClick={() => setSelected(item.date)}
            >
              <View className="day-pill__week">{weekdayLabel(index)}</View>
              <View className="day-pill__date">{formatMonthDay(item.date).replace(/\d+月/, '')}</View>
            </View>
          ))}
        </View>
      </ScrollView>

      <Card>
        <View className="card__head">
          <Text className="card__label">{formatMonthDay(selected)}</Text>
          <Text className="chip">{day?.day_type === 'weekend' ? '周末' : '工作日'}</Text>
        </View>

        {MEAL_ORDER.map((mealType) => {
          const meal = day?.meals.find((item) => item.meal_type === mealType)
          if (!meal) return null
          return (
            <View key={meal.id} className={`meal${meal.is_cooked ? ' meal--cooked' : ''}`} style={{ marginTop: 12 }}>
              <View className="meal__head">
                <Text className="meal__type">{mealLabel(meal.meal_type)}</Text>
                <View style={{ display: 'flex', gap: px(6) }}>
                  {meal.is_locked ? <Text className="chip">已锁定</Text> : null}
                  {meal.is_cooked ? <Text className="chip chip--accent">已做</Text> : null}
                </View>
              </View>
              <View className="meal__name">{meal.recipe?.name ?? '待定'}</View>
              <View className="meal__meta">
                {[
                  meal.recipe?.calories ? `${Math.round(meal.recipe.calories)} kcal` : null,
                  meal.recipe?.cook_minutes ? `${Math.round(meal.recipe.cook_minutes)} 分钟` : null,
                  meal.estimated_cost != null ? formatMoney(meal.estimated_cost) : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </View>
              {meal.recipe?.ingredients?.length ? (
                <View className="meal__ings">
                  {meal.recipe.ingredients
                    .map((ing) =>
                      ing.quantity == null ? ing.name : `${ing.name} ${ing.quantity}${ing.unit}`,
                    )
                    .join(' · ')}
                </View>
              ) : null}
              {meal.recipe?.steps ? (
                <View className="meal__ings">做法: {meal.recipe.steps.slice(0, 60)}</View>
              ) : null}
              <View className="meal__actions">
                <PillButton
                  size="sm"
                  variant="ghost"
                  onClick={() => handleReplace(meal.id, meal.recipe?.name ?? '这道菜')}
                >
                  换一道
                </PillButton>
                <PillButton size="sm" variant="ghost" onClick={() => handleLock(meal.id, meal.is_locked)}>
                  {meal.is_locked ? '解锁' : '锁定'}
                </PillButton>
                {!meal.is_cooked ? (
                  <PillButton size="sm" onClick={() => handleCook(meal.id)}>
                    做完了
                  </PillButton>
                ) : null}
              </View>
            </View>
          )
        })}
      </Card>

      <Card>
        <View className="card__head">
          <Text className="card__label">本周预算</Text>
          <Text className="card__hint" style={{ marginTop: 0 }}>
            {formatMoney(menu.budget.total_estimated)} / {formatMoney(menu.budget.budget_limit)}
          </Text>
        </View>
        <View style={{ marginTop: 10 }}>
          <Bar
            value={
              menu.budget.budget_limit
                ? (menu.budget.total_estimated / menu.budget.budget_limit) * 100
                : 0
            }
            tone={menu.budget.passed ? 'ink' : 'warn'}
          />
        </View>
        {menu.budget.suggestions?.length ? (
          <View className="card__hint">{menu.budget.suggestions[0]}</View>
        ) : null}
      </Card>

      <View style={{ marginTop: px(14), display: 'flex', gap: px(10) }}>
        <PillButton variant="gray" block disabled={busy} onClick={() => goTo('/shopping')}>
          看采购清单
        </PillButton>
        <PillButton variant="ghost" block disabled={busy} onClick={() => handleGenerate(true)}>
          重新生成
        </PillButton>
      </View>

      <View style={{ height: 24 }} />
    </View>
  )
}
