/**
 * 今日 - 打开就知道"今天吃什么、还缺什么、下一步点哪"
 *
 * 信息层级 (参考稿顺序):
 *   预算头 -> 下一步(未就绪时才出现) -> 补单决策 -> 今晚菜单 -> 自做 vs 外卖
 *   -> 本周概览磁贴 -> 今日流程时间线
 * 一屏只放一个黑色主按钮, 其余都是浅灰胶囊。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Collapse, InputNumber, message } from 'antd'
import {
  CheckOutlined,
  DownOutlined,
  RightOutlined,
  ShoppingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  Bar,
  Banner,
  Card,
  Chip,
  EmptyState,
  LoadingStack,
  NextStepCard,
  PageHead,
  PillButton,
  SectionTitle,
  StatTile,
} from '../../components/ui'
import { getToday, rememberTakeoutPrice } from '../../api/today'
import { markItemCooked, undoMarkCooked } from '../../api/menu'
import { addInventoryItem } from '../../api/inventory'
import { useMenuGeneration } from '../../hooks/useMenuGeneration'
import {
  formatAmount,
  formatKcal,
  formatMinutes,
  formatMoney,
  formatMonthDay,
  formatPercent,
  formatProgress,
  formatRemaining,
  mealLabel,
  nextStep,
  orderStatusText,
  orderSummaryText,
  takeoutHeadline,
  timelineTone,
} from '@shared/index'
import type { NextStep } from '@shared/next-step'
import type { CurrentUser, RecognitionItem, TimelineEntry, TodayOverview } from '../../types'
import RecognizePanel from '../../components/RecognizePanel'
import { toastWithUndo } from '../../lib/undo'

const TIMELINE_DOT: Record<string, string> = {
  ok: '',
  pending: 'is-pending',
  failed: 'is-failed',
  off: 'is-off',
}

function greeting(hour: number): string {
  if (hour < 5) return '夜深了'
  if (hour < 11) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
}

const Today: React.FC<{ user: CurrentUser }> = ({ user }) => {
  const navigate = useNavigate()
  const [data, setData] = useState<TodayOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [cooking, setCooking] = useState(false)
  const [takeoutPrice, setTakeoutPrice] = useState<number | null>(null)
  const [priceSaved, setPriceSaved] = useState(false)
  const [recognizeOpen, setRecognizeOpen] = useState(false)

  const load = useCallback(async () => {
    setLoadError('')
    try {
      const overview = await getToday()
      setData(overview)
      setTakeoutPrice(overview.budget.takeout_reference_price)
    } catch (error) {
      setLoadError((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const generation = useMenuGeneration(() => {
    message.success('菜单已生成')
    load()
  })

  const step = useMemo(
    () =>
      nextStep({
        hasPreferences: data?.ready.has_preferences ?? false,
        menu: data?.week
          ? {
              status: data.week.status,
              week_start_date: data.week.week_start_date,
              totals: data.week.totals,
              days: data.meals.length ? [{ date: data.date, meals: data.meals }] : [],
            }
          : null,
        shoppingToBuyCount: data?.shopping?.to_buy_count ?? 0,
        generating: generation.running,
      }),
    [data, generation.running],
  )

  const handleStepAction = (target: NextStep) => {
    if (target.isGenerateAction) {
      generation.start(undefined, false)
      return
    }
    if (target.to) navigate(target.to)
  }

  const handleCook = async () => {
    if (!data?.menu_id || !data.tonight?.meal_id) return
    const menuId = data.menu_id
    const itemId = data.tonight.meal_id
    setCooking(true)
    try {
      const result = await markItemCooked(menuId, itemId)
      await load()
      toastWithUndo({
        key: `cook-${itemId}`,
        text:
          result.missing.length > 0
            ? `已标记, ${result.missing.length} 样没扣到库存`
            : '已标记, 库存已扣减',
        onUndo: async () => {
          await undoMarkCooked(menuId, itemId)
          await load()
        },
      })
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setCooking(false)
    }
  }

  const handlePriceBlur = async () => {
    if (takeoutPrice == null || !data) return
    if (takeoutPrice === data.budget.takeout_reference_price) return
    try {
      await rememberTakeoutPrice(takeoutPrice)
      setPriceSaved(true)
      window.setTimeout(() => setPriceSaved(false), 2400)
      await load()
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleRecognized = async (items: RecognitionItem[]) => {
    let saved = 0
    for (const item of items) {
      if (!item.name || item.quantity == null) continue
      try {
        await addInventoryItem({
          ingredient_name: item.name,
          quantity: item.quantity,
          unit: item.unit || '个',
          expiry_date: item.expiry_days
            ? new Date(Date.now() + item.expiry_days * 86400000).toISOString().slice(0, 10)
            : null,
        })
        saved += 1
      } catch {
        // 单条失败不打断整体, 最后统一提示
      }
    }
    message.success(`已入库 ${saved} 样食材`)
    setRecognizeOpen(false)
    await load()
  }

  if (loading) {
    return (
      <div className="page">
        <PageHead title={`${greeting(new Date().getHours())}, ${user.name}`} />
        <LoadingStack rows={6} />
      </div>
    )
  }

  const dateLine = data
    ? `${formatMonthDay(data.date)} ${data.weekday_label} · ${
        data.day_type === 'weekend' ? '周末' : '工作日'
      }`
    : ''

  const budget = data?.budget
  const dailyBudget = budget?.daily_budget ?? 0
  const spentToday = budget?.spent_today ?? 0
  const budgetPercent = dailyBudget > 0 ? Math.round((spentToday / dailyBudget) * 100) : 0
  const notReady = !data?.ready.has_menu || !data?.ready.has_preferences

  return (
    <div className="page">
      <PageHead
        title={`${greeting(new Date().getHours())}, ${user.name}`}
        subtitle={dateLine}
      />

      {loadError && <Alert type="error" showIcon message={loadError} closable />}
      {generation.error && <Alert type="error" showIcon message={generation.error} closable />}

      {/* 预算头: 今天还能花多少 */}
      {budget && dailyBudget > 0 && (
        <Card tight className="budget-strip">
          <div className="budget-strip-head">
            <div>
              <div className="stat-label">今日预算</div>
              <div className="stat-value">
                {formatMoney(Math.max(0, budget.remaining_today ?? 0))}
                <span className="stat-unit">可用 / {formatMoney(dailyBudget)}</span>
              </div>
            </div>
            <Chip tone={budgetPercent > 100 ? 'danger' : 'gray'}>
              已用 {formatPercent(budgetPercent)}
            </Chip>
          </div>
          <Bar percent={budgetPercent} tone={budgetPercent > 100 ? 'over' : 'ink'} />
        </Card>
      )}

      <div className="bento">
        {/* 没就绪才占位提醒; 就绪后主行动交给下面的补单卡 */}
        {notReady && (
          <NextStepCard step={step} onAction={handleStepAction} loading={generation.submitting} />
        )}
      </div>

      {/* 补单决策: 今晚缺什么、够不够起送价、直接下单 */}
      {data?.order && (
        <Card className="order-card">
          <div className="card-head">
            <div>
              <div className="card-title">今晚要补 {data.order.missing_count} 样</div>
              <div className="card-sub">{orderSummaryText(data.order)}</div>
            </div>
            <Chip tone={data.order.reaches_min_order ? 'green' : 'warn'}>
              {orderStatusText(data.order)}
            </Chip>
          </div>

          <div className="order-lines">
            {data.order.items.slice(0, 6).map((line) => (
              <div key={`${line.name}-${line.is_topup}`} className="order-line">
                <span className={`order-dot ${line.is_topup ? 'is-topup' : ''}`} />
                <span className="order-name">
                  {line.name}
                  {line.is_topup && <Chip>凑单</Chip>}
                </span>
                <span className="order-amount">
                  {formatAmount(line.quantity, line.unit)}
                  <em>{line.estimated_price != null ? formatMoney(line.estimated_price) : '—'}</em>
                </span>
              </div>
            ))}
          </div>

          {data.order.note && <div className="card-sub">{data.order.note}</div>}

          <div className="stack-actions">
            <PillButton
              block
              onClick={() => {
                if (data.order?.miniapp_app_id) {
                  window.open(data.order.order_link, '_blank', 'noopener')
                  return
                }
                window.open(data.order!.order_link, '_blank', 'noopener')
              }}
            >
              <ShoppingOutlined /> 立即下单
            </PillButton>
            <PillButton variant="gray" block onClick={() => navigate('/menus')}>
              调整菜单
            </PillButton>
          </div>
        </Card>
      )}

      {/* 今晚这一餐 */}
      {data?.tonight ? (
        <Card className="tonight-card">
          <div className="card-head">
            <div>
              <div className="card-title">{data.tonight.name || '今晚还没定'}</div>
              <div className="card-sub">
                {mealLabel(data.tonight.meal_type)}
                {data.tonight.servings ? ` · ${data.tonight.servings} 人份` : ''}
                {data.tonight.cook_minutes ? ` · ${formatMinutes(data.tonight.cook_minutes)}` : ''}
              </div>
            </div>
            {data.tonight.is_cooked ? (
              <Chip tone="green">已做</Chip>
            ) : data.tonight.is_locked ? (
              <Chip>已锁定</Chip>
            ) : null}
          </div>

          <div className="meta-row">
            {data.tonight.calories != null && <span>{formatKcal(data.tonight.calories)}</span>}
            {data.tonight.protein_g != null && (
              <span>蛋白 {Math.round(data.tonight.protein_g)} g</span>
            )}
            {data.tonight.estimated_cost != null && (
              <span>约 {formatMoney(data.tonight.estimated_cost)}</span>
            )}
          </div>

          {data.tonight.uses_expiring.length > 0 && (
            <Banner
              tone="accent"
              title={`消耗临期食材 ${data.tonight.uses_expiring.length} 样`}
              text={data.tonight.uses_expiring
                .map((item) => `${item.ingredient_name}(${formatRemaining(item.days_left)})`)
                .join(' · ')}
            />
          )}

          {data.tonight.ingredients.length > 0 && (
            <Collapse
              ghost
              expandIcon={({ isActive }) => (
                <DownOutlined rotate={isActive ? 180 : 0} />
              )}
              items={[
                {
                  key: 'recipe',
                  label: `食材 ${data.tonight.ingredients.length} 样 · 做法 ${data.tonight.step_count} 步`,
                  children: (
                    <div>
                      <ul className="ingredient-list">
                        {data.tonight!.ingredients.map((ing) => (
                          <li key={ing.name}>
                            <span>{ing.name}</span>
                            <span className="ingredient-amount">
                              {formatAmount(ing.quantity, ing.unit)}
                            </span>
                          </li>
                        ))}
                      </ul>
                      {data.tonight!.steps && (
                        <div className="recipe-steps">{data.tonight!.steps}</div>
                      )}
                    </div>
                  ),
                },
              ]}
            />
          )}

          <div className="stack-actions">
            {!data.tonight.is_cooked && (
              <PillButton block loading={cooking} onClick={handleCook}>
                <CheckOutlined /> 做完了, 扣库存
              </PillButton>
            )}
            <PillButton variant="gray" block onClick={() => navigate('/menus')}>
              看整周 / 换一道
            </PillButton>
          </div>
        </Card>
      ) : (
        data?.menu_id && (
          <Card>
            <EmptyState
              title="今天没有排餐"
              description="这周的菜单里没有今天, 可以去周菜单看看, 或者换一道"
              actionLabel="看周菜单"
              onAction={() => navigate('/menus')}
            />
          </Card>
        )
      )}

      {/* 自做 vs 外卖 */}
      {data?.takeout && (
        <Card className="takeout-card">
          <div className="card-head">
            <div>
              <div className="card-title">今晚自己做饭还是点外卖</div>
              <div className="card-sub">{takeoutHeadline(data.takeout.recommended)}</div>
            </div>
            <ThunderboltOutlined className="card-head-icon" />
          </div>

          <div className="versus">
            <div
              className={`versus-side ${data.takeout.recommended === 'homemade' ? 'is-lead' : ''}`}
            >
              <div className="versus-label">自己做饭</div>
              <div className="versus-value">
                {formatMoney(data.takeout.homemade.cost)}
                <span className="stat-unit">/ {formatMinutes(data.takeout.homemade.minutes)}</span>
              </div>
            </div>
            <div className="versus-vs">VS</div>
            <div
              className={`versus-side ${data.takeout.recommended === 'takeout' ? 'is-lead' : ''}`}
            >
              <div className="versus-label">点外卖</div>
              <div className="versus-value">
                {formatMoney(data.takeout.takeout.cost)}
                <span className="stat-unit">/ {formatMinutes(data.takeout.takeout.minutes)}</span>
              </div>
            </div>
          </div>

          <div className="price-edit">
            <span>外卖参考价</span>
            <InputNumber
              value={takeoutPrice ?? undefined}
              min={0}
              max={500}
              step={1}
              size="small"
              onChange={(value) => setTakeoutPrice(value ?? 0)}
              onBlur={handlePriceBlur}
              onPressEnter={handlePriceBlur}
            />
            <span className="price-edit-hint">
              {priceSaved ? (
                <span className="is-accent">已记住, 下次默认 {formatMoney(takeoutPrice)}</span>
              ) : (
                '改完点一下别处就记住了'
              )}
            </span>
          </div>

          {data.takeout.reasons.length > 0 && (
            <ul className="reason-list">
              {data.takeout.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}

          <PillButton
            variant="gray"
            block
            onClick={() => window.open(data.takeout!.link, '_blank', 'noopener')}
          >
            {data.takeout.link_label} <RightOutlined />
          </PillButton>
        </Card>
      )}

      {/* 本周概览磁贴 */}
      <SectionTitle>本周概览</SectionTitle>
      <div className="bento">
        <StatTile
          span={2}
          lg={3}
          label="本周预算"
          value={formatMoney(data?.week?.budget.total_estimated ?? 0)}
          unit={
            (data?.week?.budget.budget_limit ?? 0) > 0
              ? `/ ${formatMoney(data?.week?.budget.budget_limit)}`
              : '未设上限'
          }
          hint={
            data?.week
              ? data.week.budget.passed
                ? `还剩 ${formatMoney(
                    Math.max(0, data.week.budget.budget_limit - data.week.budget.total_estimated),
                  )}`
                : `超出 ${formatMoney(data.week.budget.over_amount)}`
              : '生成菜单后按食材参考价估算'
          }
          hintTone={data?.week && !data.week.budget.passed ? 'danger' : 'muted'}
        >
          <Bar
            percent={
              data?.week && data.week.budget.budget_limit > 0
                ? (data.week.budget.total_estimated / data.week.budget.budget_limit) * 100
                : 0
            }
            tone={data?.week && !data.week.budget.passed ? 'over' : 'ink'}
          />
        </StatTile>

        <StatTile
          label="营养达标"
          value={data?.week ? (data.week.nutrition.passed ? '达标' : '有偏离') : '—'}
          hint={
            data?.nutrition
              ? `今天 ${Math.round(data.nutrition.calories)} / ${data.nutrition.target_calories ?? '—'} kcal`
              : '填好健康目标后按天校验'
          }
          hintTone={data?.week && !data.week.nutrition.passed ? 'warn' : 'muted'}
          lg={3}
        />

        <StatTile
          label="冰箱库存"
          value={data?.expiring.length ? data.expiring.length : '—'}
          unit={data?.expiring.length ? '样临期' : ''}
          hint={
            data?.expiring.length
              ? data.expiring.some((item) => item.used_tonight)
                ? '已有食材排进今晚菜单'
                : '去冰箱看看怎么安排'
              : '暂无临期食材'
          }
          hintTone={data?.expiring.length ? 'warn' : 'muted'}
          lg={3}
        />

        <StatTile
          span={2}
          lg={3}
          label="本周进度"
          value={data?.week ? formatProgress(data.week.totals.cooked_count, data.week.totals.meal_count) : '—'}
          hint={data?.week ? `${data.week.totals.day_count} 天菜单` : '生成后逐餐标记已做'}
          hintTone={data?.week && data.week.totals.cooked_count > 0 ? 'accent' : 'muted'}
        />
      </div>

      {/* 今日流程时间线 */}
      {data && data.timeline.length > 0 && (
        <>
          <SectionTitle>今天的自动流程</SectionTitle>
          <Card tight>
            <div className="timeline">
              {data.timeline.map((entry) => (
                <button
                  key={entry.key}
                  type="button"
                  className="timeline-row"
                  onClick={() => navigate(timelineTarget(entry))}
                >
                  <span className={`state-dot ${TIMELINE_DOT[timelineTone(entry.status)]}`} />
                  <div className="timeline-text">
                    <b>{entry.label}</b>
                    <span>{entry.detail}</span>
                  </div>
                  <span className="timeline-time">{entry.time || '完成时'}</span>
                </button>
              ))}
            </div>
          </Card>
        </>
      )}

      <div className="page-footnote">
        <button type="button" className="card-link" onClick={() => setRecognizeOpen(true)}>
          拍照入库冰箱
        </button>
        <span> · 做饭标记后会自动扣减库存, 缺料只提醒不阻断。</span>
      </div>

      <RecognizePanel
        open={recognizeOpen}
        onClose={() => setRecognizeOpen(false)}
        onConfirm={handleRecognized}
      />

      <div style={{ height: 16 }} />
    </div>
  )
}

function timelineTarget(entry: TimelineEntry): string {
  if (entry.key === 'menu_push') return '/me'
  if (entry.key === 'stock_check') return '/shopping'
  return '/menus'
}

export default Today
