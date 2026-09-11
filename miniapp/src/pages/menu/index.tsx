/**
 * 周菜单 - 星期条 + 当天全部餐次
 *
 * 交互目标 (钟老师闭环原则):
 *  - 每个操作都有即时反馈且回到稳定态, 不靠整页 reload 闪一下;
 *  - "重新生成" 只在页面底部出现一次, 不冗余;
 *  - 选了某天后能一键"回到今天", 日期导航自闭环;
 *  - "做完了" 之后 6 秒内可"撤销", 操作可逆, 形成闭环。
 *
 * 换一道 / 锁定 / 标记已做 全部走本地乐观更新: 先改本地状态让界面立刻响应,
 * 接口成功即定稿; 只有"生成菜单 / 确认菜单"这种整周级动作才重新拉取。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import type { MealDetail, MenuDay, MenuDetail, MenuSource } from '@shared/types'

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
import { askReplaceRecipe, markCooked, toggleLock, undoCook, UNDO_WINDOW_MS } from '../../lib/meal-actions'
import { startGeneration, waitForGeneration } from '../../lib/menu'

/** 生成来源 -> 展示文案与标签色 (本地多 = 好, 所以本地给 accent) */
const SOURCE_LABEL: Record<MenuSource, string> = {
  local: '本地菜谱库',
  mixed: '本地 + AI',
  ai: 'AI 生成',
}
const SOURCE_TONE: Record<MenuSource, string> = {
  local: 'chip--accent',
  mixed: 'chip--warn',
  ai: 'chip--ink',
}

export default function MenuPage() {
  const [menu, setMenu] = useState<MenuDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(todayIso())

  /** 刚"做完了"的餐次 id: 在 UNDO_WINDOW_MS 内显示"撤销", 形成可逆闭环 */
  const [undoItemId, setUndoItemId] = useState<number | null>(null)
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

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

  /** 卸载时清理撤销计时器, 避免回调打到已卸载的页面 */
  useEffect(() => {
    return () => {
      if (undoTimer.current) clearTimeout(undoTimer.current)
    }
  }, [])

  usePullDownRefresh(() => {
    void load()
  })

  const day: MenuDay | undefined = useMemo(
    () => menu?.days.find((item) => item.date === selected),
    [menu, selected],
  )

  const today = todayIso()
  const onToday = selected === today

  // ---- 本地乐观更新: 改一处餐次 / 累计已做数, 不整页 reload ----
  const patchMeal = useCallback((itemId: number, patch: Partial<MealDetail>) => {
    setMenu((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        days: prev.days.map((d) => ({
          ...d,
          meals: d.meals.map((m) => (m.id === itemId ? { ...m, ...patch } : m)),
        })),
      }
    })
  }, [])

  const bumpCooked = useCallback((delta: number) => {
    setMenu((prev) =>
      prev
        ? { ...prev, totals: { ...prev.totals, cooked_count: Math.max(0, prev.totals.cooked_count + delta) } }
        : prev,
    )
  }, [])

  const showUndo = useCallback((itemId: number) => {
    if (undoTimer.current) clearTimeout(undoTimer.current)
    setUndoItemId(itemId)
    undoTimer.current = setTimeout(() => setUndoItemId(null), UNDO_WINDOW_MS)
  }, [])

  const clearUndo = useCallback(() => {
    if (undoTimer.current) clearTimeout(undoTimer.current)
    setUndoItemId(null)
  }, [])

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
      // 确认只改状态, 本地直接翻状态即可, 不必整页 reload
      setMenu((prev) => (prev ? { ...prev, status: 'confirmed' } : prev))
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleReplace = async (meal: MealDetail) => {
    if (!menu) return
    try {
      const updated = await askReplaceRecipe(menu, meal)
      if (updated) setMenu(updated)
    } catch (err) {
      toast((err as Error).message)
    }
  }

  const handleLock = async (itemId: number, locked: boolean) => {
    if (!menu) return
    try {
      await toggleLock(menu, itemId, locked)
      // 乐观翻状态: 锁/解锁已落库, 本地立刻反映
      patchMeal(itemId, { is_locked: !locked })
    } catch (err) {
      toast((err as Error).message)
    }
  }

  const handleCook = async (itemId: number) => {
    if (!menu) return
    try {
      const changed = await markCooked(menu, itemId)
      if (changed) {
        patchMeal(itemId, { is_cooked: true })
        bumpCooked(1)
        showUndo(itemId)
      }
    } catch (err) {
      toast((err as Error).message)
    }
  }

  const handleUndo = async (itemId: number) => {
    if (!menu) return
    try {
      await undoCook(menu, itemId)
      patchMeal(itemId, { is_cooked: false })
      bumpCooked(-1)
      clearUndo()
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
          <View className="chip-row">
            <Text className={`chip ${menu.source ? SOURCE_TONE[menu.source] : 'chip--ink'}`}>
              {menu.source ? SOURCE_LABEL[menu.source] : 'AI 生成'}
            </Text>
            <Text className="chip">{menu.status === 'draft' ? '待确认' : '已确认'}</Text>
          </View>
        </View>
        <View className="card__hint">
          {menu.source === 'local' ? '全部来自本地菜谱库' : '由 AI 生成'}
          {menu.created_at ? ` · ${menu.created_at.replace('T', ' ').slice(5, 16)}` : ''}
          {' · '}预估 {formatMoney(menu.totals.estimated_cost)}
        </View>
        {menu.source === 'mixed' ? (
          <View className="card__hint">
            本地菜谱库没凑齐这一周, 缺口交给 AI 补齐了; 补齐本地库后会更省。
          </View>
        ) : null}
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
          {!onToday ? (
            <View
              className="day-pill tap day-pill--jump"
              onClick={() => setSelected(today)}
            >
              <View className="day-pill__week">今天</View>
            </View>
          ) : null}
          {menu.days.map((item, index) => {
            const isToday = item.date === today
            return (
              <View
                key={item.date}
                className={`day-pill tap${item.date === selected ? ' day-pill--active' : ''}`}
                onClick={() => setSelected(item.date)}
              >
                <View className="day-pill__week">
                  {weekdayLabel(index)}
                  {isToday ? <Text className="day-pill__today">今</Text> : null}
                </View>
                <View className="day-pill__date">{formatMonthDay(item.date).replace(/\d+月/, '')}</View>
              </View>
            )
          })}
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
          const canUndo = undoItemId === meal.id
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
                <PillButton size="sm" variant="ghost" onClick={() => handleReplace(meal)}>
                  换一道
                </PillButton>
                <PillButton size="sm" variant="ghost" onClick={() => handleLock(meal.id, meal.is_locked)}>
                  {meal.is_locked ? '解锁' : '锁定'}
                </PillButton>
                {!meal.is_cooked ? (
                  <PillButton size="sm" onClick={() => handleCook(meal.id)}>
                    做完了
                  </PillButton>
                ) : canUndo ? (
                  <PillButton size="sm" variant="ghost" onClick={() => handleUndo(meal.id)}>
                    撤销
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
