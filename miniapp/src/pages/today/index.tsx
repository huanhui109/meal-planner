/**
 * 今日 - 打开就知道"今天吃什么、还缺什么、下一步点哪"
 *
 * 信息层级与 H5 的 pages/Today 完全一致 (同一套 shared 决策与文案):
 *   预算头 -> 下一步(未就绪才有) -> 补单决策 -> 今晚菜单 -> 自做 vs 外卖
 *   -> 本周概览 -> 今日流程时间线
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useShareAppMessage } from '@tarojs/taro'

import { formatAmount, formatMoney, formatMinutes, formatProgress, formatPercent } from '@shared/format'
import { mealLabel } from '@shared/labels'
import { nextStep } from '@shared/next-step'
import { orderStatusText, orderSummaryText, takeoutHeadline, timelineTone } from '@shared/today'
import type { RecognitionItem, TimelineEntry, TodayOverview } from '@shared/types'

import {
  Bar,
  BentoCell,
  BentoGrid,
  Banner,
  Card,
  EmptyState,
  LoadingStack,
  NextStepCard,
  PageHead,
  PillButton,
  SectionTitle,
  StatTile,
} from '../../components/ui'
import { addInventory, getToday, rememberTakeoutPrice } from '../../lib/api'
import { ensureLogin, syncTabBar, toast } from '../../lib/nav'
import { openPurchaseLink, missingText } from '../../lib/deeplink'
import { getCachedUser, isOnboarded } from '../../lib/session'
import { markCooked } from '../../lib/meal-actions'
import { track } from '../../lib/events'
import { RecognizeSheet } from '../../components/recognize-sheet'

const TIMELINE_DOT: Record<string, string> = {
  ok: 'ok',
  pending: 'off',
  failed: 'warn',
  off: 'off',
}

function greeting(): string {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 11) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
}

export default function TodayPage() {
  const [data, setData] = useState<TodayOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [recognizeOpen, setRecognizeOpen] = useState(false)

  /** 页面卸载后丢弃 setState, 避免 "setState on unmounted" 警告 */
  const aliveRef = useRef(true)
  useEffect(() => () => { aliveRef.current = false }, [])

  const user = getCachedUser()

  const load = useCallback(async () => {
    if (!ensureLogin()) return
    setError('')
    try {
      const next = await getToday()
      // 卸载/再次进入页面后丢弃旧请求结果
      if (!aliveRef.current) return
      setData(next)
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
    syncTabBar(0)
    // audit T2.1: 未走完引导就 reLaunch 到 onboarding
    if (!isOnboarded()) {
      Taro.reLaunch({ url: '/pages/onboarding/index' })
      return
    }
    void load()
  })

  usePullDownRefresh(() => {
    void load()
  })

  // 分享给好友 (audit F3): 标题带"今天吃 X", 落地路径带 share_from
  useShareAppMessage(() => {
    const user = getCachedUser()
    const name = data?.tonight?.name || '待定'
    return {
      title: `今天吃「${name}」, 帮你算好预算 · 每周鲜`,
      path: `/pages/today/index?share_from=${encodeURIComponent(user?.open_id || 'friend')}&share_date=${data?.date || ''}`,
    }
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
        generating: busy,
      }),
    [data, busy],
  )

  const handleGenerate = async () => {
    setBusy(true)
    try {
      const { startGeneration, waitForGeneration } = await import('../../lib/menu')
      const accepted = await startGeneration(data?.week?.week_start_date ?? '')
      if (!accepted.task_id) {
        await load()
        return
      }
      const task = await waitForGeneration(accepted.task_id)
      toast(task.status === 'failed' ? task.error || '生成失败' : '菜单生成好了', task.status === 'failed' ? 'none' : 'success')
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleStepAction = () => {
    if (step.isGenerateAction) return handleGenerate()
    if (step.to) {
      const map: Record<string, string> = {
        '/preferences': '/pages/profile/index',
        '/menus': '/pages/menu/index',
        '/shopping': '/pages/shopping/index',
        '/inventory': '/pages/fridge/index',
      }
      const target = map[step.to] || step.to
      const tabPages = ['/pages/menu/index', '/pages/shopping/index', '/pages/fridge/index']
      if (tabPages.includes(target)) Taro.switchTab({ url: target })
      else Taro.navigateTo({ url: target })
    }
  }

  const handleCook = async () => {
    if (!data?.menu_id || !data.tonight?.meal_id) return
    setBusy(true)
    try {
      const menuLike = {
        id: data.menu_id,
      } as never
      await markCooked(menuLike as never, data.tonight.meal_id)
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleOrder = async () => {
    if (!data?.order) return
    track('order_open', {
      platform: data.order.platform ?? null,
      item_count: data.order.items?.length ?? 0,
    })
    await openPurchaseLink({
      miniappAppId: data.order.miniapp_app_id,
      link: data.order.order_link,
      copyText: missingText(data.order.items),
    })
  }

  const openRecognize = () => {
    track('recognize_open', { source: 'today' })
    setRecognizeOpen(true)
  }

  const handlePriceChange = async () => {
    if (!data) return
    const modal = (await Taro.showModal({
      title: '外卖参考价',
      editable: true,
      placeholderText: `现在 ${data.budget.takeout_reference_price} 元一顿`,
      confirmText: '记住',
      cancelText: '取消',
    } as never)) as unknown as { confirm: boolean; content?: string }
    if (!modal.confirm) return
    const price = Number((modal.content || '').trim())
    if (!Number.isFinite(price) || price < 0 || price > 500) {
      toast('请填 0-500 之间的数字')
      return
    }
    try {
      await rememberTakeoutPrice(price)
      toast(`已记住 ${formatMoney(price)}`, 'success')
      await load()
    } catch (err) {
      toast((err as Error).message)
    }
  }

  const handleRecognized = async (items: RecognitionItem[]) => {
    let saved = 0
    for (const item of items) {
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
        <PageHead title={`${greeting()}, ${user?.name ?? ''}`} />
        <LoadingStack rows={5} />
      </View>
    )
  }

  const budget = data?.budget
  const dailyBudget = budget?.daily_budget ?? 0
  const spentToday = budget?.spent_today ?? 0
  const budgetPercent = dailyBudget > 0 ? Math.round((spentToday / dailyBudget) * 100) : 0
  const notReady = !data?.ready.has_menu || !data?.ready.has_preferences

  return (
    <View className="page">
      <PageHead
        title={`${greeting()}, ${user?.name ?? '你'}`}
        subtitle={
          data
            ? `${data.date.slice(5)} ${data.weekday_label} · ${data.day_type === 'weekend' ? '周末' : '工作日'}`
            : ''
        }
        action={
          <View
            className="page-head__action tap"
            onClick={() => Taro.navigateTo({ url: '/pages/profile/index' })}
          >
            {user?.name?.[0] ?? '我'}
          </View>
        }
      />

      {!!error && <Banner tone="warn">{error}</Banner>}

      {budget && dailyBudget > 0 ? (
        <Card>
          <View className="card__head">
            <Text className="card__label">今日预算</Text>
            <Text className="chip">已用 {formatPercent(budgetPercent)}</Text>
          </View>
          <View className="card__value card__value--sm">
            <Text className="num">
              {formatMoney(Math.max(0, budget.remaining_today ?? 0))}
            </Text>
            <Text className="card__unit">可用 / {formatMoney(dailyBudget)}</Text>
          </View>
          <View style={{ marginTop: 12 }}>
            <Bar value={budgetPercent} tone={budgetPercent > 100 ? 'warn' : 'ink'} />
          </View>
        </Card>
      ) : null}

      {notReady ? (
        <NextStepCard
          title={step.title}
          description={step.description}
          actionLabel={step.actionLabel}
          loading={busy}
          onAction={handleStepAction}
        />
      ) : null}

      {data?.order ? (
        <Card>
          <View className="card__head">
            <Text className="card__label">今晚要补 {data.order.missing_count} 样</Text>
            <Text className={`chip chip--${data.order.reaches_min_order ? 'accent' : 'warn'}`}>
              {orderStatusText(data.order)}
            </Text>
          </View>
          <View className="card__hint">{orderSummaryText(data.order)}</View>
          <View className="order-lines">
            {data.order.items.slice(0, 6).map((line, index) => (
              <View
                key={`${line.ingredient_id ?? line.name}-${line.is_topup}-${index}`}
                className="order-line"
              >
                <View className={`order-dot${line.is_topup ? ' order-dot--topup' : ''}`} />
                <Text className="order-line__name">
                  {line.name}
                  {line.is_topup ? ' (凑单)' : ''}
                </Text>
                <Text className="order-line__amount">
                  {line.estimated_price != null ? formatMoney(line.estimated_price) : '—'}
                </Text>
              </View>
            ))}
          </View>
          {!!data.order.note && <View className="card__hint">{data.order.note}</View>}
          <View style={{ marginTop: 12 }}>
            <PillButton block onClick={handleOrder}>
              立即下单
            </PillButton>
          </View>
          <View style={{ marginTop: 8 }}>
            <PillButton variant="gray" block onClick={() => Taro.switchTab({ url: '/pages/menu/index' })}>
              调整菜单
            </PillButton>
          </View>
        </Card>
      ) : null}

      {data?.tonight ? (
        <Card>
          <View className="card__head">
            <Text className="card__label">{data.tonight.name || '今晚还没定'}</Text>
            {data.tonight.is_cooked ? (
              <Text className="chip chip--accent">已做</Text>
            ) : data.tonight.is_locked ? (
              <Text className="chip">已锁定</Text>
            ) : null}
          </View>
          <View className="card__hint">
            {[
              mealLabel(data.tonight.meal_type),
              data.tonight.servings ? `${data.tonight.servings} 人份` : null,
              data.tonight.cook_minutes ? formatMinutes(data.tonight.cook_minutes) : null,
              data.tonight.calories != null ? `${Math.round(data.tonight.calories)} kcal` : null,
              data.tonight.protein_g != null ? `蛋白 ${Math.round(data.tonight.protein_g)} g` : null,
              data.tonight.estimated_cost != null ? `约 ${formatMoney(data.tonight.estimated_cost)}` : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </View>

          {data.tonight.uses_expiring.length > 0 ? (
            <Banner tone="accent">
              消耗临期食材:{' '}
              {data.tonight.uses_expiring
                .map((item) => `${item.ingredient_name}(剩 ${item.days_left} 天)`)
                .join(' · ')}
            </Banner>
          ) : null}

          <View className="meal__ings">
            {data.tonight.ingredients.map((ing) => (
              <Text key={ing.name} className="meal__ing">
                {ing.name} {formatAmount(ing.quantity, ing.unit)}
              </Text>
            ))}
          </View>

          {!data.tonight.is_cooked ? (
            <View style={{ marginTop: 12 }}>
              <PillButton block disabled={busy} onClick={handleCook}>
                做完了, 扣库存
              </PillButton>
            </View>
          ) : null}
          <View style={{ marginTop: 8 }}>
            <PillButton variant="gray" block onClick={() => Taro.switchTab({ url: '/pages/menu/index' })}>
              看整周 / 换一道
            </PillButton>
          </View>
        </Card>
      ) : data?.menu_id ? (
        <Card>
          <EmptyState
            title="今天没有排餐"
            description="这周的菜单里没有今天, 去周菜单看看"
            actionLabel="看周菜单"
            onAction={() => Taro.switchTab({ url: '/pages/menu/index' })}
          />
        </Card>
      ) : null}

      {data?.takeout ? (
        <Card>
          <Text className="card__label">今晚自己做饭还是点外卖</Text>
          <View className="card__hint">{takeoutHeadline(data.takeout.recommended)}</View>
          <View className="versus">
            <View className={`versus__side${data.takeout.recommended === 'homemade' ? ' versus__side--lead' : ''}`}>
              <Text className="versus__label">自己做饭</Text>
              <Text className="versus__value">
                {formatMoney(data.takeout.homemade.cost)}
                <Text className="versus__unit">
                  {' '}
                  {formatMinutes(data.takeout.homemade.minutes)}
                </Text>
              </Text>
            </View>
            <Text className="versus__vs">VS</Text>
            <View className={`versus__side${data.takeout.recommended === 'takeout' ? ' versus__side--lead' : ''}`}>
              <Text className="versus__label">点外卖</Text>
              <Text className="versus__value">
                {formatMoney(data.takeout.takeout.cost)}
                <Text className="versus__unit">
                  {' '}
                  {formatMinutes(data.takeout.takeout.minutes)}
                </Text>
              </Text>
            </View>
          </View>
          <View className="price-edit" onClick={handlePriceChange}>
            <Text>外卖参考价 {formatMoney(data.budget.takeout_reference_price)}</Text>
            <Text className="price-edit__hint">点一下改价, 会记住</Text>
          </View>
          {data.takeout.reasons.map((reason) => (
            <Text key={reason} className="reason-line">
              · {reason}
            </Text>
          ))}
        </Card>
      ) : null}

      <SectionTitle text="本周概览" hint={data?.week ? undefined : '先生成菜单'} />
      <BentoGrid>
        <BentoCell wide>
          <Card>
            <View className="card__head">
              <Text className="card__label">本周预算</Text>
              <Text className="card__hint" style={{ marginTop: 0 }}>
                {data?.week
                  ? data.week.budget.passed
                    ? `还剩 ${formatMoney(Math.max(0, data.week.budget.budget_limit - data.week.budget.total_estimated))}`
                    : `超 ${formatMoney(data.week.budget.over_amount)}`
                  : '暂无'}
              </Text>
            </View>
            <View className="card__value card__value--sm">
              <Text className="num">
                {formatMoney(data?.week?.budget.total_estimated ?? 0)}
              </Text>
              <Text className="card__unit">/ {formatMoney(data?.week?.budget.budget_limit ?? 0)}</Text>
            </View>
            <View style={{ marginTop: 12 }}>
              <Bar
                value={
                  data?.week && data.week.budget.budget_limit > 0
                    ? (data.week.budget.total_estimated / data.week.budget.budget_limit) * 100
                    : 0
                }
                tone={data?.week && !data.week.budget.passed ? 'warn' : 'ink'}
              />
            </View>
          </Card>
        </BentoCell>

        <BentoCell>
          <StatTile
            label="营养达标"
            value={data?.week ? (data.week.nutrition.passed ? '达标' : '偏差') : '--'}
            tone={data?.week?.nutrition.passed ? 'accent' : 'warn'}
            hint={
              data?.nutrition
                ? `今天 ${Math.round(data.nutrition.calories)} kcal`
                : '暂无数据'
            }
          />
        </BentoCell>

        <BentoCell>
          <StatTile
            label="冰箱临期"
            value={`${data?.expiring.length ?? 0}`}
            unit="样"
            tone={data?.expiring.length ? 'warn' : 'ink'}
            hint={
              data?.expiring.some((item) => item.used_tonight)
                ? '已排入今晚'
                : '3 天内到期'
            }
            onClick={() => Taro.switchTab({ url: '/pages/fridge/index' })}
          />
        </BentoCell>

        <BentoCell wide>
          <Card>
            <View className="card__head">
              <Text className="card__label">本周进度</Text>
              <Text className="card__hint" style={{ marginTop: 0 }}>
                {data?.week
                  ? formatProgress(data.week.totals.cooked_count, data.week.totals.meal_count)
                  : '0/0 餐'}
              </Text>
            </View>
            <View style={{ marginTop: 12 }}>
              <Bar
                value={
                  data?.week?.totals.meal_count
                    ? (data.week.totals.cooked_count / data.week.totals.meal_count) * 100
                    : 0
                }
                tone="accent"
              />
            </View>
          </Card>
        </BentoCell>
      </BentoGrid>

      {data && data.timeline.length > 0 ? (
        <>
          <SectionTitle text="今天的自动流程" />
          <Card tight>
            <View className="set-group">
              {data.timeline.map((entry: TimelineEntry) => (
                <View key={entry.key} className="set-row">
                  <View className={`state-dot state-dot--${TIMELINE_DOT[timelineTone(entry.status)]}`} />
                  <Text className="set-row__label">
                    {entry.label} · {entry.detail}
                  </Text>
                  <Text className="set-row__value">{entry.time || '完成时'}</Text>
                </View>
              ))}
            </View>
          </Card>
        </>
      ) : null}

      <View style={{ marginTop: 12 }}>
        <PillButton variant="ghost" block onClick={openRecognize}>
          拍照入库冰箱
        </PillButton>
      </View>

      <RecognizeSheet
        open={recognizeOpen}
        onClose={() => setRecognizeOpen(false)}
        onConfirm={handleRecognized}
      />

      <View style={{ height: 24 }} />
    </View>
  )
}
