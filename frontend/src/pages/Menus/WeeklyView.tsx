/**
 * 周菜单 - UI Demo 版式
 *
 * 结构照 《饭决 UI Demo.html》:
 *   page-head (标题 + 重新排一周) → week-summary 3 统计 (预算 bar / 冰箱优先 / 本周进度)
 *   → days 7 天 strip (今天圆点) → 选中日卡片 (.meal-row: 换一道 / 锁定 / 做完了, done=删除线)
 *
 * 数据与交互逻辑不变: 换一道仍走后端 replaceMenuItem (先本地菜谱库, 挑不到再 AI),
 * 锁定/做完了/撤销与原来一致。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Modal, Spin, message } from 'antd'
import { LoadingStack } from '../../components/ui'
import { listInventory } from '../../api/inventory'
import {
  confirmMenu,
  currentWeekStart,
  getCurrentMenu,
  lockMenuItem,
  markItemCooked,
  replaceMenuItem,
  undoMarkCooked,
  unlockMenuItem,
} from '../../api/menu'
import { useMenuGeneration } from '../../hooks/useMenuGeneration'
import { toastWithUndo } from '../../lib/undo'
import {
  DAY_TYPE_LABELS,
  MENU_STATUS_LABELS,
  WEEKDAY_LABELS,
  formatDateRange,
  formatKcal,
  formatMoney,
  formatMonthDay,
  mealLabel,
  todayIso,
} from '@shared/index'
import type { MealDetail, MenuDetail } from '../../types'

/** 「换一道」走的路径 -> 展示文案 */
const REPLACE_SOURCE_LABELS: Record<string, string> = {
  local: '本地菜谱库',
  ai: 'AI 生成',
  restore: '换回上一道',
  manual: '指定菜名',
}

const WeeklyView: React.FC = () => {
  const [menu, setMenu] = useState<MenuDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyItemId, setBusyItemId] = useState<number | null>(null)
  const [replaceTarget, setReplaceTarget] = useState<MealDetail | null>(null)
  /** 换完后的那一餐与来源, 用于弹框展示结果 */
  const [replaceResult, setReplaceResult] = useState<MealDetail | null>(null)
  const [replaceSource, setReplaceSource] = useState<string | null>(null)
  const [replacing, setReplacing] = useState(false)
  const [selectedDate, setSelectedDate] = useState('')
  const [confirming, setConfirming] = useState(false)
  /** 冰箱临期数 —— 「冰箱优先」那格要看它, 拉不到就显示 — */
  const [expiringCount, setExpiringCount] = useState<number | null>(null)
  const menuId = menu?.id

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getCurrentMenu()
      setMenu(data)
      setSelectedDate((prev) => {
        if (prev && data.days.some((day) => day.date === prev)) return prev
        const today = todayIso()
        if (data.days.some((day) => day.date === today)) return today
        return data.days[0]?.date ?? ''
      })
    } catch {
      setMenu(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    listInventory()
      .then((view) => setExpiringCount(view.expiring_count))
      .catch(() => setExpiringCount(null))
  }, [])

  const generation = useMenuGeneration(() => {
    message.success('菜单已生成')
    load()
  })

  const selectedDay = useMemo(
    () => menu?.days.find((day) => day.date === selectedDate) ?? menu?.days[0] ?? null,
    [menu, selectedDate],
  )

  const withItem = async (itemId: number, action: () => Promise<void>, successText: string) => {
    setBusyItemId(itemId)
    try {
      await action()
      message.success(successText)
      if (menuId) setMenu(await getCurrentMenu())
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setBusyItemId(null)
    }
  }

  const handleLockToggle = (meal: MealDetail) =>
    withItem(
      meal.id,
      async () => {
        if (!menuId) return
        if (meal.is_locked) await unlockMenuItem(menuId, meal.id)
        else await lockMenuItem(menuId, meal.id)
      },
      meal.is_locked ? '已解锁' : '已锁定, 重新生成时不会改动这一餐',
    )

  const handleCooked = async (meal: MealDetail) => {
    if (!menuId) return
    setBusyItemId(meal.id)
    try {
      const result = await markItemCooked(menuId, meal.id)
      setMenu(await getCurrentMenu())
      toastWithUndo({
        key: `cook-${meal.id}`,
        text:
          result.missing.length > 0
            ? `已扣减库存, ${result.missing.length} 项食材不足`
            : result.consumed.length > 0
              ? `已扣减 ${result.consumed.length} 项库存`
              : '已标记完成',
        onUndo: async () => {
          await undoMarkCooked(menuId, meal.id)
          setMenu(await getCurrentMenu())
        },
      })
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setBusyItemId(null)
    }
  }

  /** 点「换一道」: 后端先查本地菜谱库, 挑不到再 AI 生成; 弹框先转圈再给结果 */
  const openReplace = async (meal: MealDetail) => {
    if (!menuId) return
    setReplaceTarget(meal)
    setReplaceResult(null)
    setReplaceSource(null)
    setReplacing(true)
    try {
      const updated = await replaceMenuItem(menuId, meal.id, {})
      setMenu(updated)
      setReplaceSource(updated.replacement?.source ?? null)
      setReplaceResult(
        updated.days.flatMap((day) => day.meals).find((row) => row.id === meal.id) ?? null,
      )
    } catch (err) {
      if (err instanceof Error) message.error(err.message)
      setReplaceTarget(null)
    } finally {
      setReplacing(false)
    }
  }

  /**
   * 关掉「换一道」弹窗
   *
   * ⚠ 之前 onCancel 只是 setReplaceTarget(null): 替换在**打开弹窗那一刻就已经写库**
   *   (openReplace 里直接 replaceMenuItem), 用户按 X / 遮罩 / ESC 关掉后, 新菜已经生效,
   *   而「换回上一道」和撤销 Toast 都只在「就它了」路径上给 —— 上一道菜就这么没了,
   *   还不知道怎么找回来。
   *
   * 现在关闭 = 放弃这次替换, 自动换回上一道 (与 Modal 的取消语义一致)。
   * 想保留新菜就点「就它了」。
   */
  const closeReplace = () => {
    const target = replaceTarget
    const previous = target?.recipe
    const current = replaceResult?.recipe
    setReplaceTarget(null)
    setReplaceResult(null)
    setReplaceSource(null)
    if (!menuId || !target || !previous || !current) return
    if (current.id === previous.id) return
    setReplacing(true)
    replaceMenuItem(menuId, target.id, { recipe_id: previous.id })
      .then((updated) => setMenu(updated))
      .catch((err: unknown) => {
        if (err instanceof Error) message.error(err.message)
      })
      .finally(() => setReplacing(false))
  }

  /** 就它了: 关掉弹框, 保留原来 5 秒可撤销的 Toast */
  const acceptReplace = () => {
    const target = replaceTarget
    const previous = target?.recipe
    const current = replaceResult?.recipe
    setReplaceTarget(null)
    setReplaceResult(null)
    setReplaceSource(null)
    if (!menuId || !target || !previous || !current) return
    toastWithUndo({
      key: `replace-${target.id}`,
      text: `已换成「${current.name}」`,
      onUndo: async () => {
        setMenu(await replaceMenuItem(menuId, target.id, { recipe_id: previous.id }))
      },
    })
  }

  /** 换回上一道: 直接切回原菜谱, 不走 AI */
  const revertReplace = async () => {
    const target = replaceTarget
    const previous = target?.recipe
    if (!menuId || !target || !previous) return
    setReplacing(true)
    try {
      const updated = await replaceMenuItem(menuId, target.id, { recipe_id: previous.id })
      setMenu(updated)
      message.success('已换回上一道')
      setReplaceTarget(null)
      setReplaceResult(null)
      setReplaceSource(null)
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setReplacing(false)
    }
  }

  const handleConfirm = async () => {
    if (!menuId) return
    setConfirming(true)
    try {
      await confirmMenu(menuId)
      message.success('已确认本周菜单')
      setMenu(await getCurrentMenu())
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setConfirming(false)
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1>本周菜单</h1>
          </div>
        </div>
        <LoadingStack rows={6} />
      </div>
    )
  }

  if (!menu || !selectedDay) {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1>本周菜单</h1>
            <p>还没有菜单, 先生成一份再回来调整</p>
          </div>
        </div>
        {generation.error && <Alert type="error" showIcon message={generation.error} closable />}
        <div className="card">
          <div className="empty-state">
            <p>这周还没有菜单</p>
            <p className="card-sub" style={{ marginTop: 6 }}>
              AI 会按你的偏好排好 7 天, 生成后可以逐餐替换、锁定和标记已做
            </p>
            <div className="decision-actions" style={{ justifyContent: 'center' }}>
              <button
                type="button"
                className="button primary"
                disabled={generation.submitting}
                onClick={() => generation.start()}
              >
                {generation.submitting ? '生成中…' : '生成菜单'}
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const weekEndDate = menu.days[menu.days.length - 1]?.date ?? menu.week_start_date
  const budgetLimit = menu.budget.budget_limit ?? 0
  const spent = menu.budget.total_estimated ?? 0
  const budgetPercent = budgetLimit > 0 ? (spent / budgetLimit) * 100 : 0
  const today = todayIso()

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>本周菜单</h1>
          <p>
            {formatDateRange(menu.week_start_date, weekEndDate)} ·{' '}
            {MENU_STATUS_LABELS[menu.status] ?? menu.status} · 先看每天，再改具体一餐
          </p>
        </div>
        <div className="page-head-actions">
          {menu.status === 'draft' && (
            <button
              type="button"
              className="button small"
              disabled={confirming}
              onClick={() => void handleConfirm()}
            >
              {confirming ? '确认中…' : '确认菜单'}
            </button>
          )}
          <button
            type="button"
            className="button small primary"
            disabled={generation.submitting}
            onClick={() => generation.start(currentWeekStart(), true)}
          >
            重新排一周
          </button>
        </div>
      </div>

      {generation.error && <Alert type="error" showIcon message={generation.error} closable />}
      {generation.running && (
        <Alert
          type="info"
          showIcon
          message="AI 正在生成菜单, 通常 1-2 分钟, 可以先去其他页面"
        />
      )}

      <div className="week-summary">
        <div className="stat">
          <div className="stat-label">本周预算</div>
          <div className="stat-value">
            {formatMoney(spent)}
            {budgetLimit > 0 && (
              <small style={{ display: 'inline', fontSize: 13 }}> / {formatMoney(budgetLimit)}</small>
            )}
          </div>
          <div className={`bar ${menu.budget.passed ? '' : 'is-over'}`}>
            <i style={{ width: `${Math.max(0, Math.min(100, budgetPercent))}%` }} />
          </div>
          <small>
            {budgetLimit > 0
              ? menu.budget.passed
                ? `还剩 ${formatMoney(Math.max(0, budgetLimit - spent))}，可以放心加一道`
                : `超出 ${formatMoney(menu.budget.over_amount)}，换掉一两道贵的菜`
              : '没设预算上限, 去偏好里补一个'}
          </small>
        </div>
        <div className="stat">
          <div className="stat-label">冰箱优先</div>
          <div className="stat-value">{expiringCount ?? '—'} 样</div>
          <small>{expiringCount ? '临期食材会优先排进菜单' : '暂无临期食材'}</small>
        </div>
        <div className="stat">
          <div className="stat-label">本周进度</div>
          <div className="stat-value">
            {menu.totals.cooked_count} / {menu.totals.meal_count}
          </div>
          <small>做完后自动扣库存</small>
        </div>
      </div>

      <div className="days">
        {menu.days.map((day) => (
          <button
            key={day.date}
            type="button"
            className={`day ${day.date === selectedDay.date ? 'active' : ''}`}
            onClick={() => setSelectedDate(day.date)}
          >
            <span>{WEEKDAY_LABELS[day.weekday]}</span>
            <b>{Number(day.date.slice(8, 10))}</b>
            {day.date === today ? <i className="dot" /> : null}
          </button>
        ))}
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <div className="card-title">
              {WEEKDAY_LABELS[selectedDay.weekday]} · {formatMonthDay(selectedDay.date)}
            </div>
            <div className="card-sub">
              {selectedDay.date === today ? '今天' : DAY_TYPE_LABELS[selectedDay.day_type] ?? ''} ·{' '}
              {selectedDay.meals.length} 餐 · 预计 {formatMoney(selectedDay.estimated_cost)}
            </div>
          </div>
          <span className={`tag ${selectedDay.date === today ? 'good' : ''}`}>
            {selectedDay.date === today ? '今天' : '已安排'}
          </span>
        </div>

        {selectedDay.meals.length === 0 ? (
          <div className="empty-state">
            这一天没有排餐
            <div className="card-sub" style={{ marginTop: 6 }}>
              可以重新生成, 或到偏好里调整每日餐次
            </div>
          </div>
        ) : (
          <div className="meal-list">
            {selectedDay.meals.map((meal) => (
              <div key={meal.id} className={`meal-row ${meal.is_cooked ? 'done' : ''}`}>
                <div className="meal-slot">{mealLabel(meal.meal_type).slice(0, 1)}</div>
                <div className="meal-info">
                  <b>{meal.recipe?.name ?? '未安排'}</b>
                  <div className="meal-meta">
                    <span>{mealLabel(meal.meal_type)}</span>
                    {meal.recipe?.calories ? <span>{formatKcal(meal.recipe.calories)}</span> : null}
                    {meal.estimated_cost ? <span>≈{formatMoney(meal.estimated_cost)}</span> : null}
                    {meal.is_locked ? <span>已锁定</span> : null}
                  </div>
                </div>
                <div className="meal-actions">
                  <button
                    type="button"
                    className="button small"
                    disabled={busyItemId === meal.id}
                    onClick={() => void openReplace(meal)}
                  >
                    换一道
                  </button>
                  <button
                    type="button"
                    className="button small"
                    disabled={busyItemId === meal.id}
                    onClick={() => void handleLockToggle(meal)}
                  >
                    {meal.is_locked ? '解锁' : '锁定'}
                  </button>
                  <button
                    type="button"
                    className={`button small ${meal.is_cooked ? '' : 'primary'}`}
                    disabled={busyItemId === meal.id || meal.is_cooked}
                    onClick={() => void handleCooked(meal)}
                  >
                    {meal.is_cooked ? '已做' : '做完了'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="page-footnote">
        换一道只影响这一餐; 锁定后的餐次在重新生成时会原样保留。
      </div>

      <Modal
        title="换一道"
        open={Boolean(replaceTarget)}
        onCancel={closeReplace}
        footer={
          replacing
            ? null
            : [
                ...(replaceResult && replaceTarget?.recipe
                  ? [
                      <Button key="revert" onClick={revertReplace}>
                        换回上一道
                      </Button>,
                    ]
                  : []),
                <Button key="ok" type="primary" onClick={acceptReplace} disabled={!replaceResult}>
                  就它了
                </Button>,
              ]
        }
      >
        {replacing ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 0' }}>
            <Spin />
            <span>正在换一道…</span>
          </div>
        ) : replaceResult?.recipe ? (
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>
              {replaceResult.recipe.name}{' '}
              <span className={`tag ${replaceSource === 'local' ? 'good' : ''}`}>
                {REPLACE_SOURCE_LABELS[replaceSource ?? ''] ?? '已替换'}
              </span>
            </div>
            <div className="meal-meta" style={{ marginTop: 6 }}>
              {replaceResult.recipe.calories ? (
                <span>{formatKcal(replaceResult.recipe.calories)}</span>
              ) : null}
              {replaceResult.estimated_cost ? (
                <span>≈{formatMoney(replaceResult.estimated_cost)}</span>
              ) : null}
            </div>
          </div>
        ) : (
          <div style={{ padding: '12px 0' }}>没有换到合适的菜, 可以再试一次。</div>
        )}
      </Modal>
    </div>
  )
}

export default WeeklyView
