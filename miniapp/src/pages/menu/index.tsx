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
import { Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useShareAppMessage } from '@tarojs/taro'

import {
  currentWeekStart,
  formatDateRange,
  formatMoney,
  formatMonthDay,
  todayIso,
  weekEnd,
} from '@shared/format'
import { MEAL_ORDER, mealLabel, weekdayLabel } from '@shared/labels'
import type { MealDetail, MenuDay, MenuDetail } from '@shared/types'
import { brand } from '@shared/brand'

import {
  Banner,
  Card,
  LoadingStack,
  PageHead,
  PillButton,
} from '../../components/ui'
import { SearchBar } from '../../components/search-bar'
import { confirmMenu, getCurrentMenu, listInventory } from '../../lib/api'
import { ensureLogin, goTo, syncTabBar, toast } from '../../lib/nav'
import { px } from '../../lib/px'
import { askReplaceRecipe, markCooked, toggleLock, undoCook, UNDO_WINDOW_MS } from '../../lib/meal-actions'
import { track } from '../../lib/events'
import { startGeneration, waitForGeneration } from '../../lib/menu'
import { useThemeClass } from '../../lib/theme'

export default function MenuPage() {
  const themeClass = useThemeClass()
  const [menu, setMenu] = useState<MenuDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(todayIso())
  /** 搜索关键字 (audit T3.4) */
  const [keyword, setKeyword] = useState('')

  /** 冰箱临期数: 「冰箱优先」stat 用, 拿不到就显示 0 */
  const [expiringCount, setExpiringCount] = useState(0)

  /** 刚"做完了"的餐次 id: 在 UNDO_WINDOW_MS 内显示"撤销", 形成可逆闭环 */
  const [undoItemId, setUndoItemId] = useState<number | null>(null)
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  /** 页面卸载后丢弃 setState, 避免 "setState on unmounted" 警告 */
  const aliveRef = useRef(true)
  useEffect(() => () => { aliveRef.current = false }, [])

  const load = useCallback(async () => {
    if (!ensureLogin()) return
    setError('')
    // 「冰箱优先」stat 的点缀数据, 失败不影响菜单
    void listInventory()
      .then((view) => {
        if (aliveRef.current) setExpiringCount(view.expiring_count ?? 0)
      })
      .catch(() => undefined)
    try {
      const data = await getCurrentMenu()
      if (!aliveRef.current) return
      setMenu(data)
      if (data && !data.days.some((day) => day.date === selected)) {
        setSelected(data.days[0]?.date ?? selected)
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

  // 分享给好友 (audit F3): 标题带周次, path 加 share_from 让对方看到「XX 转给你的」banner
  useShareAppMessage(() => {
    const meals = menu?.days?.reduce((sum, day) => sum + (day.meals?.length || 0), 0) || 0
    const weekLabel = menu?.week_start_date ? `这周 ${menu.week_start_date.slice(5)}` : '这周'
    return {
      title: `${weekLabel} 一共 ${meals} 餐, 营养 / 预算都算好 · ${brand.name}`,
      path: `/pages/menu/index?share_from=${encodeURIComponent(menu?.id ? `menu-${menu.id}` : 'friend')}&share_week=${menu?.week_start_date || ''}`,
    }
  })

  const day: MenuDay | undefined = useMemo(
    () => menu?.days.find((item) => item.date === selected),
    [menu, selected],
  )

  /** 搜索过滤 (audit T3.4): 命中菜名或任一食材名即保留 */
  const shownMeals = useMemo(() => {
    const all = day?.meals ?? []
    if (!keyword) return all
    const kw = keyword.toLowerCase()
    return all.filter((m) => {
      if (m.recipe?.name?.toLowerCase().includes(kw)) return true
      return (m.recipe?.ingredients ?? []).some((i) => i.name?.toLowerCase().includes(kw))
    })
  }, [day, keyword])

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
    track('generate_menu', { week_start: currentWeekStart(), force })
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

  const openRecipeDetail = (meal: MealDetail, menuId: number) => {
    if (!meal.recipe) {
      toast('这道菜还没有菜谱信息')
      return
    }
    track('recipe_detail_open', { menu_id: menuId, meal_id: meal.id })
    const payload = {
      meal_id: meal.id,
      menu_id: menuId,
      meal_type: meal.meal_type,
      name: meal.recipe.name,
      steps: meal.recipe.steps ?? null,
      cuisine: meal.recipe.cuisine ?? null,
      difficulty: meal.recipe.difficulty ?? null,
      cook_minutes: meal.recipe.cook_minutes ?? null,
      calories: meal.recipe.calories ?? null,
      protein_g: meal.recipe.protein_g ?? null,
      carb_g: meal.recipe.carb_g ?? null,
      fat_g: meal.recipe.fat_g ?? null,
      estimated_cost: meal.estimated_cost ?? null,
      is_cooked: meal.is_cooked,
      ingredients: (meal.recipe.ingredients ?? []).map((i) => ({
        name: i.name,
        quantity: i.quantity ?? null,
        unit: i.unit ?? null,
      })),
    }
    Taro.navigateTo({
      url: `/pages/recipe-detail/index?data=${encodeURIComponent(JSON.stringify(payload))}`,
    })
  }

  const handleReplace = async (meal: MealDetail) => {
    if (!menu) return
    track('replace_item', { menu_id: menu.id, meal_id: meal.id })
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
      <View className={`page ${themeClass}`}>
        <PageHead title="周菜单" subtitle="正在读取本周安排…" />
        <LoadingStack rows={4} />
      </View>
    )
  }

  if (!menu) {
    return (
      <View className={`page ${themeClass}`}>
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

  const budgetPct =
    menu.budget.budget_limit > 0
      ? Math.round((menu.budget.total_estimated / menu.budget.budget_limit) * 100)
      : 0

  return (
    <View className={`page ${themeClass}`}>
      <PageHead
        title="本周菜单"
        subtitle={`${formatDateRange(menu.week_start_date, weekEnd(menu.week_start_date))} · 先看每天，再改具体一餐`}
        action={
          <View className={`d-btn d-btn--sm tap${busy ? ' d-btn--disabled' : ''}`} onClick={() => !busy && handleGenerate(true)}>
            <Text>重新排一周</Text>
          </View>
        }
      />

      {error ? <Banner tone="danger">{error}</Banner> : null}

      {/* Demo week-summary: 本周预算(带 bar) + 冰箱优先 + 本周进度 */}
      <View className="d-week-summary">
        <View className="d-stat d-stat--wide">
          <View className="d-stat-label">本周预算</View>
          <View className="d-stat-value">
            {formatMoney(menu.budget.total_estimated)}{' '}
            <Text className="d-stat-value__unit">/ {formatMoney(menu.budget.budget_limit)}</Text>
          </View>
          <View className="d-bar">
            <View
              className={`d-bar__fill${menu.budget.passed ? '' : ' d-bar__fill--warn'}`}
              style={{ width: `${Math.min(100, budgetPct)}%` }}
            />
          </View>
          <View className="d-stat-small">
            {menu.budget.passed
              ? `还剩 ${formatMoney(Math.max(0, menu.budget.budget_limit - menu.budget.total_estimated))}，可以放心加一道`
              : `超出 ${formatMoney(menu.budget.over_amount)}，换掉一两道贵的菜就能压回来`}
          </View>
        </View>
        <View className="d-stat">
          <View className="d-stat-label">冰箱优先</View>
          <View className="d-stat-value">{expiringCount} 样</View>
          <View className="d-stat-small">临期食材会优先排进餐单</View>
        </View>
        <View className="d-stat">
          <View className="d-stat-label">本周进度</View>
          <View className="d-stat-value">
            {menu.totals.cooked_count} / {menu.totals.meal_count}
          </View>
          <View className="d-stat-small">做完后自动扣库存</View>
        </View>
      </View>

      {/* 搜索 (audit T3.4): 命中菜名或食材名即过滤当天菜品 */}
      <View style={{ marginBottom: 12 }}>
        <SearchBar
          placeholder="搜菜名或食材 (如: 番茄)"
          value={keyword}
          onChange={setKeyword}
        />
      </View>
      {keyword ? (
        <View className="card__hint" style={{ marginBottom: 8 }}>
          匹配「{keyword}」的餐次: {shownMeals.length} 个
          {shownMeals.length === 0 ? ' · 换个关键词试试' : ''}
        </View>
      ) : null}

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

      {/* Demo days strip: 7 天按钮, 今天带绿点 */}
      <View className="d-days">
        {menu.days.map((item, index) => {
          const isToday = item.date === today
          return (
            <View
              key={item.date}
              className={`d-day tap${item.date === selected ? ' d-day--active' : ''}`}
              onClick={() => setSelected(item.date)}
            >
              <Text className="d-day__week">{weekdayLabel(index)}</Text>
              <Text className="d-day__date">{Number(item.date.slice(8, 10))}</Text>
              {isToday ? <View className="d-day__dot" /> : null}
            </View>
          )
        })}
      </View>

      {/* Demo selected-day 卡片: 头部 + meal-rows */}
      <View className="d-card">
        <View className="d-card-head">
          <View>
            <View className="d-card-title">
              {day ? `${weekdayLabel(menu.days.indexOf(day))} · ${formatMonthDay(selected)}` : formatMonthDay(selected)}
            </View>
            <View className="d-card-sub">
              {day?.day_type === 'weekend' ? '周末' : '工作日'} · {day?.meals.length ?? 0} 餐 · 预计 {formatMoney(day?.estimated_cost ?? 0)}
            </View>
          </View>
          <Text className={`d-tag${onToday ? ' d-tag--good' : ''}`}>{onToday ? '今天' : '已安排'}</Text>
        </View>

        <View>
          {MEAL_ORDER.map((mealType) => {
            const meal = shownMeals.find((item) => item.meal_type === mealType)
            if (!meal) return null
            const canUndo = undoItemId === meal.id
            return (
              <View key={meal.id} className={`d-meal-row${meal.is_cooked ? ' d-meal-row--done' : ''}`}>
                <View className="d-meal-slot">{mealLabel(meal.meal_type).slice(0, 1)}</View>
                <View className="d-meal-info">
                  <View className="d-meal-name" onClick={() => openRecipeDetail(meal, menu.id)}>
                    {meal.recipe?.name ?? '待定'}
                  </View>
                  <View className="d-meal-meta">
                    {[
                      meal.recipe?.calories ? `${Math.round(meal.recipe.calories)} kcal` : null,
                      meal.estimated_cost != null ? formatMoney(meal.estimated_cost) : null,
                      meal.is_locked ? '已锁定' : null,
                    ]
                      .filter(Boolean)
                      .map((part) => (
                        <Text key={part as string}>{part}</Text>
                      ))}
                  </View>
                </View>
                <View className="d-meal-actions">
                  <View className="d-btn d-btn--sm tap" onClick={() => handleReplace(meal)}>
                    <Text>换一道</Text>
                  </View>
                  <View className="d-btn d-btn--sm tap" onClick={() => handleLock(meal.id, meal.is_locked)}>
                    <Text>{meal.is_locked ? '解锁' : '锁定'}</Text>
                  </View>
                  {!meal.is_cooked ? (
                    <View className="d-btn d-btn--sm d-btn--primary tap" onClick={() => handleCook(meal.id)}>
                      <Text>做完了</Text>
                    </View>
                  ) : canUndo ? (
                    <View className="d-btn d-btn--sm d-btn--ghost tap" onClick={() => handleUndo(meal.id)}>
                      <Text>撤销</Text>
                    </View>
                  ) : (
                    <View className="d-btn d-btn--sm d-btn--disabled">
                      <Text>已做</Text>
                    </View>
                  )}
                </View>
              </View>
            )
          })}
        </View>
      </View>

      <View style={{ marginTop: px(14) }}>
        <PillButton variant="gray" block disabled={busy} onClick={() => goTo('/shopping')}>
          看采购清单
        </PillButton>
      </View>

      <View style={{ height: 24 }} />
    </View>
  )
}
