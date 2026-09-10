import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Collapse, Form, Input, InputNumber, Modal, message } from 'antd'
import { CheckCircleOutlined, LockOutlined, UnlockOutlined } from '@ant-design/icons'
import {
  Bar,
  Card,
  Chip,
  DayStrip,
  EmptyState,
  LoadingStack,
  PageHead,
  PillButton,
} from '../../components/ui'
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
import { getAutomationStatus } from '../../api/automation'
import { useMenuGeneration } from '../../hooks/useMenuGeneration'
import { toastWithUndo } from '../../lib/undo'
import {
  DAY_TYPE_LABELS,
  MENU_STATUS_LABELS,
  WEEKDAY_LABELS,
  formatAmount,
  formatDateRange,
  formatKcal,
  formatMinutes,
  formatMoney,
  formatMonthDay,
  formatProgress,
  mealLabel,
  todayIso,
} from '@shared/index'
import type { MealDetail, MenuDetail } from '../../types'

const WeeklyView: React.FC = () => {
  const [menu, setMenu] = useState<MenuDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyItemId, setBusyItemId] = useState<number | null>(null)
  const [replaceTarget, setReplaceTarget] = useState<MealDetail | null>(null)
  const [replacing, setReplacing] = useState(false)
  const [selectedDate, setSelectedDate] = useState('')
  const [confirming, setConfirming] = useState(false)
  /** 周生成时间文案来自调度配置, 拉不到就用默认说法, 不影响页面 */
  const [weeklyGeneration, setWeeklyGeneration] = useState('每周日 20:00')
  const [form] = Form.useForm()

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
    getAutomationStatus()
      .then((status) => {
        if (status.reminders.weekly_generation) {
          setWeeklyGeneration(status.reminders.weekly_generation)
        }
      })
      .catch(() => undefined)
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

  const submitReplace = async () => {
    if (!menuId || !replaceTarget) return
    const target = replaceTarget
    const previous = target.recipe
    try {
      const values = await form.validateFields()
      setReplacing(true)
      const updated = await replaceMenuItem(menuId, target.id, {
        recipe_name: values.recipe_name,
        calories: values.calories ?? 0,
        cook_minutes: values.cook_minutes ?? 20,
        steps: values.steps ?? '',
      })
      setMenu(updated)
      setReplaceTarget(null)
      form.resetFields()
      // 换一道也做成可撤销: 弹层里再放一个「换回上一道」会挤, 放 Toast 更顺手
      if (previous) {
        toastWithUndo({
          key: `replace-${target.id}`,
          text: `已换成「${values.recipe_name}」`,
          onUndo: async () => {
            setMenu(
              await replaceMenuItem(menuId, target.id, {
                recipe_name: previous.name,
                calories: previous.calories ?? 0,
                cook_minutes: previous.cook_minutes ?? 20,
                steps: previous.steps ?? '',
              }),
            )
          },
        })
      } else {
        message.success('已替换这一餐')
      }
    } catch (err) {
      if (err instanceof Error) message.error(err.message)
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
        <PageHead title="本周菜单" />
        <LoadingStack rows={6} />
      </div>
    )
  }

  if (!menu || !selectedDay) {
    return (
      <div className="page">
        <PageHead title="本周菜单" subtitle="还没有菜单, 先生成一份再回来调整" />
        {generation.error && <Alert type="error" showIcon message={generation.error} closable />}
        <Card>
          <EmptyState
            title="这周还没有菜单"
            description="AI 会按你的偏好排好 7 天, 生成后可以逐餐替换、锁定和标记已做"
            actionLabel="生成菜单"
            loading={generation.submitting}
            onAction={() => generation.start()}
          />
        </Card>
      </div>
    )
  }

  const weekEnd = menu.days[menu.days.length - 1]?.date ?? menu.week_start_date
  const cookedToday = selectedDay.meals.filter((meal) => meal.is_cooked).length

  return (
    <div className="page">
      <PageHead
        title="本周菜单"
        subtitle={`${formatDateRange(menu.week_start_date, weekEnd)} · ${MENU_STATUS_LABELS[menu.status] ?? menu.status} · 预估 ${formatMoney(
          menu.totals.estimated_cost,
        )} · 进度 ${formatProgress(menu.totals.cooked_count, menu.totals.meal_count)}`}
        extra={
          <>
            {menu.status === 'draft' && (
              <PillButton variant="gray" size="sm" loading={confirming} onClick={handleConfirm}>
                确认菜单
              </PillButton>
            )}
          </>
        }
      />

      {generation.error && <Alert type="error" showIcon message={generation.error} closable />}
      {generation.running && (
        <Alert
          type="info"
          showIcon
          message="AI 正在生成菜单, 通常 1-2 分钟, 可以先去其他页面"
        />
      )}

      <WeekSummary
        menu={menu}
        generatedLabel={weeklyGeneration}
        onRegenerate={() => generation.start(currentWeekStart(), true)}
        regenerating={generation.submitting}
      />

      <DayStrip
        days={menu.days.map((day) => ({
          date: day.date,
          weekday: day.weekday,
          isToday: day.date === todayIso(),
        }))}
        selected={selectedDay.date}
        onSelect={setSelectedDate}
      />

      <Card>
        <div className="card-head">
          <div>
            <div className="card-title">
              {WEEKDAY_LABELS[selectedDay.weekday]} · {formatMonthDay(selectedDay.date)}
            </div>
            <div className="card-sub">
              {DAY_TYPE_LABELS[selectedDay.day_type] ?? ''} · {selectedDay.meals.length} 餐 · 已做{' '}
              {cookedToday}/{selectedDay.meals.length} · ≈
              {formatMoney(selectedDay.estimated_cost)}
            </div>
          </div>
        </div>

        {selectedDay.meals.length === 0 ? (
          <EmptyState title="这一天没有排餐" description="可以重新生成, 或到偏好里调整每日餐次" />
        ) : (
          <div className="meal-list">
            {selectedDay.meals.map((meal) => (
              <MealBlock
                key={meal.id}
                meal={meal}
                busy={busyItemId === meal.id}
                onLockToggle={handleLockToggle}
                onCooked={handleCooked}
                onReplace={(target) => {
                  setReplaceTarget(target)
                  form.setFieldsValue({
                    recipe_name: '',
                    calories: target.recipe?.calories ?? 350,
                    cook_minutes: target.recipe?.cook_minutes ?? 20,
                    steps: '',
                  })
                }}
              />
            ))}
          </div>
        )}
      </Card>

      <div className="section-title">整周</div>
      <Card tight>
        <div className="set-group">
          {menu.days.map((day) => (
            <button
              key={day.date}
              type="button"
              className="set-row"
              style={{ width: '100%', border: 'none', background: 'none', textAlign: 'left' }}
              onClick={() => setSelectedDate(day.date)}
            >
              <div className="set-icon">{day.weekday + 1}</div>
              <div className="set-text">
                <b>
                  {WEEKDAY_LABELS[day.weekday]} {day.date.slice(5)}
                  {day.date === todayIso() && <span className="chip chip--green" style={{ marginLeft: 6 }}>今天</span>}
                </b>
                <span>
                  {day.meals.length === 0
                    ? '没有排餐'
                    : day.meals
                        .map((meal) => meal.recipe?.name ?? '(未安排)')
                        .join(' · ')}
                </span>
              </div>
              <div className="set-value">≈{formatMoney(day.estimated_cost)}</div>
            </button>
          ))}
        </div>
      </Card>

      <div className="page-footnote">
        换一道只影响这一餐; 锁定后的餐次在重新生成时会原样保留。
      </div>

      <Modal
        title="换一道菜"
        open={Boolean(replaceTarget)}
        onCancel={() => setReplaceTarget(null)}
        onOk={submitReplace}
        confirmLoading={replacing}
        okText="替换"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="recipe_name"
            label="新菜名"
            rules={[{ required: true, message: '请输入菜名' }]}
          >
            <Input placeholder="例如: 番茄牛腩" />
          </Form.Item>
          <div className="field-grid">
            <Form.Item name="calories" label="热量 (kcal)">
              <InputNumber min={0} max={3000} placeholder="350" style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="cook_minutes" label="烹饪时间 (分钟)">
              <InputNumber min={1} max={300} placeholder="20" style={{ width: '100%' }} />
            </Form.Item>
          </div>
          <Form.Item name="steps" label="做法 (可选)">
            <Input.TextArea rows={3} placeholder="简要步骤" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

interface WeekSummaryProps {
  menu: MenuDetail
  generatedLabel: string
  onRegenerate: () => void
  regenerating: boolean
}

/** 周头: 日期 + 生成时间 + 预算进度 + 周均营养目标 + 重新生成 */
const WeekSummary: React.FC<WeekSummaryProps> = ({
  menu,
  generatedLabel,
  onRegenerate,
  regenerating,
}) => {
  const budgetLimit = menu.budget.budget_limit ?? 0
  const spent = menu.budget.total_estimated ?? 0
  const percent = budgetLimit > 0 ? (spent / budgetLimit) * 100 : 0
  const nutrition = menu.nutrition
  const days = nutrition.daily ?? []
  const avg = (pick: (day: (typeof days)[number]) => number) =>
    days.length ? Math.round(days.reduce((sum, day) => sum + pick(day), 0) / days.length) : 0
  const generatedAt = menu.created_at
    ? `${menu.created_at.replace('T', ' ').slice(5, 16)}`
    : generatedLabel
  const atLabel = /^\d/.test(generatedAt) ? generatedAt : `于${generatedAt}`

  return (
    <Card className="week-summary">
      <div className="card-head">
        <div>
          <div className="card-title">这周总览</div>
          <div className="card-sub">
            {formatDateRange(menu.week_start_date, menu.days[menu.days.length - 1]?.date ?? menu.week_start_date)}
            {' · '}由 AI {atLabel} 生成
          </div>
        </div>
        <Chip tone={menu.status === 'draft' ? 'warn' : 'green'}>
          {MENU_STATUS_LABELS[menu.status] ?? menu.status}
        </Chip>
      </div>

      <div className="week-grid">
        <div className="week-stat">
          <div className="stat-label">本周预算</div>
          <div className="stat-value">
            {formatMoney(spent)}
            <span className="stat-unit">
              {budgetLimit > 0 ? `/ ${formatMoney(budgetLimit)}` : '未设上限'}
            </span>
          </div>
          <Bar percent={percent} tone={menu.budget.passed ? 'ok' : 'over'} />
          <div className={`stat-hint ${menu.budget.passed ? '' : 'is-danger'}`}>
            {menu.budget.passed
              ? `还剩 ${formatMoney(Math.max(0, budgetLimit - spent))} 可以花`
              : `超出 ${formatMoney(menu.budget.over_amount)}, 换掉一两道贵的菜就能压回来`}
          </div>
        </div>

        <div className="week-stat">
          <div className="stat-label">周均营养目标</div>
          <div className="stat-value">
            {Math.round(nutrition.weekly_avg_calories)}
            <span className="stat-unit">
              kcal / 日{nutrition.target_calories ? ` · 目标 ${nutrition.target_calories}` : ''}
            </span>
          </div>
          <div className="macro-legend">
            <div>
              <span>蛋白</span>
              <b>{avg((day) => day.protein_pct)}%</b>
            </div>
            <div>
              <span>碳水</span>
              <b>{avg((day) => day.carb_pct)}%</b>
            </div>
            <div>
              <span>脂肪</span>
              <b>{avg((day) => day.fat_pct)}%</b>
            </div>
          </div>
          <div className={`stat-hint ${nutrition.passed ? '' : 'is-warn'}`}>
            {nutrition.passed ? '整周热量与三大营养素都在目标区间内' : nutrition.issues[0] ?? '有偏离'}
          </div>
        </div>
      </div>

      <div className="stack-actions">
        <PillButton variant="gray" block loading={regenerating} onClick={onRegenerate}>
          重新生成 (锁定的餐次原样保留)
        </PillButton>
      </div>
    </Card>
  )
}

interface MealBlockProps {
  meal: MealDetail
  busy: boolean
  onLockToggle: (meal: MealDetail) => void
  onCooked: (meal: MealDetail) => void
  onReplace: (meal: MealDetail) => void
}

const MealBlock: React.FC<MealBlockProps> = ({
  meal,
  busy,
  onLockToggle,
  onCooked,
  onReplace,
}) => (
  <div className="meal">
    <div className="meal-head">
      <div className="meal-tag">{mealLabel(meal.meal_type).slice(0, 1)}</div>
      <div className="meal-info">
        <div className="meal-name">
          {meal.recipe?.name ?? '未安排'}
          {meal.is_locked && <Chip>已锁定</Chip>}
          {meal.is_cooked && <Chip tone="green">已做</Chip>}
        </div>
        <div className="meal-meta">
          <span>{mealLabel(meal.meal_type)}</span>
          {meal.recipe?.cook_minutes ? <span>{formatMinutes(meal.recipe.cook_minutes)}</span> : null}
          {meal.recipe?.calories ? <span>{formatKcal(meal.recipe.calories)}</span> : null}
          {meal.estimated_cost ? <span>≈{formatMoney(meal.estimated_cost)}</span> : null}
        </div>
      </div>
      <div className="meal-actions">
        <button type="button" className="pill pill--gray pill--sm" onClick={() => onReplace(meal)}>
          换一道
        </button>
        <button
          type="button"
          className="pill pill--gray pill--sm"
          disabled={busy}
          onClick={() => onLockToggle(meal)}
        >
          {meal.is_locked ? <UnlockOutlined /> : <LockOutlined />}
        </button>
        <button
          type="button"
          className={`pill pill--sm ${meal.is_cooked ? 'pill--gray' : 'pill--ink'}`}
          disabled={busy || meal.is_cooked}
          onClick={() => onCooked(meal)}
        >
          {meal.is_cooked ? <CheckCircleOutlined /> : '做完了'}
        </button>
      </div>
    </div>

    {meal.recipe && meal.recipe.ingredients.length > 0 && (
      <div className="meal-extra">
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: meal.id,
              label: `食材 (${meal.recipe.ingredients.length}) 与做法`,
              children: (
                <>
                  <ul className="ingredient-list">
                    {meal.recipe.ingredients.map((ingredient) => (
                      <li key={`${meal.id}-${ingredient.name}`}>
                        <span>{ingredient.name}</span>
                        <span className="ingredient-amount">
                          {formatAmount(ingredient.quantity, ingredient.unit)}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {meal.recipe.steps && <div className="recipe-steps">{meal.recipe.steps}</div>}
                </>
              ),
            },
          ]}
        />
      </div>
    )}
  </div>
)

export default WeeklyView
