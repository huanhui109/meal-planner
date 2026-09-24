/**
 * 今日 - 三段式首页: 首屏只做一件事(定这一顿), 次屏才放"决定之后"的事
 *
 * 首屏(不滚动可见, ≤1.5 屏):
 *   ① 状态行「19:20 · 晚餐 · 家里有 6 样」  ← 替代问候语, 餐次由钟点推断不给选
 *   ② 决策区 DecideBoard                    ← 全页唯一黑色主按钮
 *   ③ 一条浅色出口「不想做饭？点外卖 →」
 *
 * 次屏(决策之后才关心的事):
 *   ④ 「家里有啥」快选  ⑤ 今晚这一餐(做完了扣库存的落点)
 *   〔折叠〕今日预算条 —— 深夜(22:00-05:00)完全不渲染
 *
 * 从首页移走的模块与理由:
 *   - 问候语:       「晚上好, 小明」占两行但零信息量, 换成状态行后同高度多两个有效信息
 *   - 周概览 4 磁贴: 旧内核「每周鲜」残留, 每次出现都在制造"我还有一整周要规划"的焦虑。
 *                   移到周菜单页, 想看的人会自己去
 *   - 今日流程时间线: 那是**系统**的自动化日志, 不是用户要做的事。移到「我的 → 运行状态」
 *   - 自做 vs 外卖对比卡: 降级成 ③ 那一行文字链。能打开饭决的人已经是"愿意做"的人,
 *                   这张卡越强越是在给外卖导流
 *   - 下一步引导卡:   onboarding 残留。它挡在主按钮下方 = 告诉用户"你还有一步要做",
 *                   直接违反"打开就能定"(本地池 ≥60 道已经保证永远有答案)
 *
 * 判断标准(用来砍模块): 一个模块如果不能帮助用户在 2 秒内定下"这一顿", 它就不该在首页。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useDidHide, useDidShow, usePullDownRefresh, useShareAppMessage } from '@tarojs/taro'

import { brand } from '@shared/brand'
import { resolveMealSlot } from '@shared/decide'
import { contextBucket, shouldShowBudgetStrip } from '@shared/decide-context'
import { formatAmount, formatKcal, formatMoney, formatPercent } from '@shared/format'
import { mealLabel } from '@shared/labels'
import type { InventoryItem, RecognitionItem, TodayOverview } from '@shared/types'

import { Bar, Banner, Card, EmptyState, LoadingStack, PageHead, PillButton, SectionTitle } from '../../components/ui'
import { addInventory, getToday, listInventory, rememberTakeoutPrice } from '../../lib/api'
import { ensureLogin, syncTabBar, toast } from '../../lib/nav'
import { openPurchaseLink } from '../../lib/deeplink'
import { getCachedUser } from '../../lib/session'
import { getUserSettings, markGuideAutoShown, shouldAutoShowGuideNow } from '../../lib/user-settings'
import { markCooked } from '../../lib/meal-actions'
import { track, flushNow } from '../../lib/track'
import { useThemeClass } from '../../lib/theme'
import { RecognizeSheet } from '../../components/recognize-sheet'
import DecideBoard from '../../components/decide-board'
import HomeStatusBar from '../../components/home-status-bar'
import FridgeQuickAdd from '../../components/fridge-quick-add'
import Splash from '../../components/splash'
import { peekResult } from '../../lib/decide'

/**
 * Taro 的 showModal 类型没带 editable / placeholderText / content, 但微信基础库支持。
 * 这里用局部类型增强补上, 比 `as never` + `as unknown as` 双重强转安全 ——
 * 已知的 title / confirmText 等字段仍然参与类型检查 (audit B4)。
 *
 * 注意: iOS 14 以下会忽略 editable, 只显示普通弹窗, 不崩 (audit B6, 平台限制)。
 */
type EditableModalOption = Taro.showModal.Option & {
  editable?: boolean
  placeholderText?: string
}
type EditableModalResult = Taro.showModal.SuccessCallbackResult & { content?: string }

export default function TodayPage() {
  const themeClass = useThemeClass()
  const [data, setData] = useState<TodayOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [fridge, setFridge] = useState<InventoryItem[] | null>(null)
  const [budgetOpen, setBudgetOpen] = useState(false)
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

  const loadFridge = useCallback(async () => {
    // 冰箱数据拿不到不影响决策, 失败就当"家里有啥"没录过
    try {
      const view = await listInventory()
      if (!aliveRef.current) return
      setFridge(view.items)
    } catch {
      if (aliveRef.current) setFridge(null)
    }
  }, [])

  useDidShow(() => {
    syncTabBar(0)
    // 引导不再写死成"没走过就必须看": 由用户在「我的 → 用户信息」里配置的开关和展示时机决定
    // (shared/user-settings.ts 的 shouldAutoShowGuide)。默认 once —— 走完一次就不再打扰。
    //
    // ⚠ 必须用 shouldAutoShowGuideNow 而不是 shouldAutoShowGuide:
    //   后者只看配置, 不知道"本次启动已经弹过了"。用户在引导里答完 3 题点「进饭决」
    //   reLaunch 回本页, 而 reLaunch **不重建 JS 上下文**, 于是这里再判一次
    //   "该展示引导" 又把人 reLaunch 回引导页 —— 反复回到引导问题界面, 永远进不去主页。
    //   showMode=每次启动 时必现; once 模式下 completed 写失败 (storage 满/被拒) 也必现。
    //   shouldAutoShowGuideNow 多一层「一次启动只弹一次」的闸门, 挡住这条回弹路径。
    if (shouldAutoShowGuideNow(getUserSettings())) {
      markGuideAutoShown()
      Taro.reLaunch({ url: '/pages/onboarding/index' })
      return
    }
    void load()
    void loadFridge()
  })

  usePullDownRefresh(() => {
    void load()
    void loadFridge()
  })

  // 退出/切后台前把攒下的埋点发出去, 否则最后一次决策的事件会丢
  useDidHide(() => {
    flushNow()
  })

  /**
   * 首页曝光: 只打一次 —— 它是"打开首页"这个事实, 不是"数据刷回来了"这个事实。
   * 所以要等首屏数据落定再打, 否则 has_profile / has_fridge 全是猜的。
   */
  const homeViewSent = useRef(false)
  useEffect(() => {
    if (homeViewSent.current || loading) return
    homeViewSent.current = true
    track('home_view', {
      meal_slot: resolveMealSlot(),
      bucket: contextBucket(),
      has_profile: data?.ready.has_preferences ?? null,
      has_fridge: (fridge?.length ?? 0) > 0,
      has_last_result: Boolean(peekResult()),
    })
  }, [loading, data, fridge])

  // 分享给好友 (audit F3): 标题带"今天吃 X", 落地路径带 share_from
  useShareAppMessage(() => {
    const name = data?.tonight?.name || '待定'
    return {
      title: `饭决说今天吃「${name}」 · ${brand.name}`,
      path: `/pages/today/index?share_from=${encodeURIComponent(user?.open_id || 'friend')}&share_date=${data?.date || ''}`,
    }
  })

  const handleCook = async () => {
    if (!data?.menu_id || !data.tonight?.meal_id) return
    setBusy(true)
    try {
      await markCooked({ id: data.menu_id }, data.tonight.meal_id)
      toast('已标记, 库存已扣减', 'success')
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleTakeout = () => {
    if (!data?.takeout) return
    track('home_takeout_exit', { meal_slot: resolveMealSlot() })
    void openPurchaseLink({
      miniappAppId: data.takeout.miniapp_app_id,
      link: data.takeout.link,
      copyText: data.takeout.link_label || data.takeout.link,
    })
  }

  const handlePriceChange = async () => {
    if (!data) return
    const modal = (await Taro.showModal({
      title: '外卖参考价',
      editable: true,
      placeholderText: `现在 ${data.budget.takeout_reference_price} 元一顿`,
      confirmText: '记住',
      cancelText: '取消',
    } as EditableModalOption)) as EditableModalResult
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
    await loadFridge()
  }

  if (loading) {
    return (
      <View className={`page ${themeClass}`}>
        <PageHead title={brand.name} />
        <LoadingStack rows={4} />
      </View>
    )
  }

  const budget = data?.budget
  const dailyBudget = budget?.daily_budget ?? 0
  const spentToday = budget?.spent_today ?? 0
  const budgetPercent = dailyBudget > 0 ? Math.round((spentToday / dailyBudget) * 100) : 0
  /**
   * 预算条:
   *   - 深夜(22:00-05:00)**完全不渲染** —— 那时候给用户看"预算已用 87%"不是提醒是添堵
   *   - 其余时段默认折叠: 单餐预算是事后校验不是事前闸门
   * 判定一律走 shared/decide-context.ts, 这里不写 `hour >= 22`。
   */
  const showBudget = shouldShowBudgetStrip() && dailyBudget > 0
  const tonight = data?.tonight
  // 深夜不出现热量/营养: 说教类信息在深夜是添堵
  const showTonightKcal = shouldShowBudgetStrip()

  return (
    <View className={`page ${themeClass}`}>
      <PageHead
        title={brand.name}
        action={
          <View
            className="page-head__action tap"
            onClick={() => Taro.navigateTo({ url: '/pages/profile/index' })}
          >
            {user?.name?.[0] ?? '我'}
          </View>
        }
      />

      {/* 品牌启动页: 覆盖层实现, 不动 entryPagePath (老用户冷启动不会重走引导) */}
      <Splash />

      {/* ① 状态行: 一行三件事(时间 · 餐次 · 家里有啥), 替代原来的两行问候语 */}
      <HomeStatusBar fridgeCount={fridge?.length ?? null} />

      {!!error && <Banner tone="warn">{error}</Banner>}

      {/*
        ② 饭决主决策区: 首页唯一主按钮。
        放在最上面是因为用户打开小程序的第一个诉求就是"今天吃什么",
        其余都是"已经决定之后"才关心的事, 全部下沉。
      */}
      <DecideBoard />

      {/* ③ 模式出口: 浅色文字链, 不是按钮。
          这个判断用户 1 秒就做完了, 做成带 VS 布局的对比卡是在逼他重做一遍。
          保留出口(它是真实需求), 砍掉对比。 */}
      {data?.takeout ? (
        <View className="home-takeout" onClick={handleTakeout}>
          <Text className="home-takeout__text">不想做饭？点外卖 →</Text>
        </View>
      ) : null}

      {/* ④ 「家里有啥」: 次屏第一个, 因为它是"做"这个模式的合法性证明 */}
      <SectionTitle text="家里有啥" />
      <Card tight>
        <FridgeQuickAdd items={fridge ?? []} onChanged={loadFridge} />
      </Card>

      {/* ⑤ 今晚这一餐: 决策后的"做完了扣库存"落点 */}
      {tonight ? (
        <Card>
          <View className="card__head">
            <Text className="card__label">{tonight.name || '今晚还没定'}</Text>
            {tonight.is_cooked ? (
              <Text className="chip chip--accent">已做</Text>
            ) : tonight.is_locked ? (
              <Text className="chip">已锁定</Text>
            ) : null}
          </View>
          <View className="card__hint">
            {mealLabel(tonight.meal_type)}
            {tonight.servings ? ` · ${tonight.servings} 人份` : ''}
          </View>

          {showTonightKcal && tonight.calories != null ? (
            <View className="meta-row">
              <Text className="meta-row__item">{formatKcal(tonight.calories)}</Text>
              {tonight.protein_g != null ? (
                <Text className="meta-row__item">蛋白 {Math.round(tonight.protein_g)} g</Text>
              ) : null}
              {tonight.estimated_cost != null ? (
                <Text className="meta-row__item">约 {formatMoney(tonight.estimated_cost)}</Text>
              ) : null}
            </View>
          ) : null}

          {tonight.uses_expiring.length > 0 ? (
            <Banner tone="accent">
              消耗临期食材:{' '}
              {tonight.uses_expiring
                .map((item) => `${item.ingredient_name}(剩 ${item.days_left} 天)`)
                .join(' · ')}
            </Banner>
          ) : null}

          {tonight.ingredients.length > 0 ? (
            <View className="meal__ings">
              {tonight.ingredients.map((ing) => (
                <Text key={ing.name} className="meal__ing">
                  {ing.name} {formatAmount(ing.quantity, ing.unit)}
                </Text>
              ))}
            </View>
          ) : null}

          <View style={{ marginTop: 12 }}>
            {!tonight.is_cooked ? (
              <PillButton block disabled={busy} onClick={handleCook}>
                做完了, 扣库存
              </PillButton>
            ) : null}
          </View>
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

      {/* 〔折叠〕今日预算条: 单餐预算是事后校验不是事前闸门, 默认收起; 深夜不渲染 */}
      {showBudget && budget ? (
        <Card>
          <View className="collapse-head" onClick={() => setBudgetOpen((prev) => !prev)}>
            <Text className="collapse-head__text">今日预算 · 已用 {formatPercent(budgetPercent)}</Text>
            <Text className="collapse-head__arrow">{budgetOpen ? '收起' : '展开'}</Text>
          </View>
          {budgetOpen ? (
            <View className="collapse-body">
              <View className="card__value card__value--sm">
                <Text className="num">{formatMoney(Math.max(0, budget.remaining_today ?? 0))}</Text>
                <Text className="card__unit">可用 / {formatMoney(dailyBudget)}</Text>
              </View>
              <View style={{ marginTop: 12 }}>
                <Bar value={budgetPercent} tone={budgetPercent > 100 ? 'warn' : 'ink'} />
              </View>
            </View>
          ) : null}
        </Card>
      ) : null}

      {/* 页脚: 拍照入库 + 外卖参考价。位置不动, 都是文字链不是按钮 */}
      <View className="page-footnote">
        <Text
          className="page-footnote__link"
          onClick={() => {
            // 沿用旧事件名: 这条链路的埋点在改版前就有, 别因为搬位置把它丢了
            track('recognize_open', { source: 'today' })
            setRecognizeOpen(true)
          }}
        >
          拍照入库冰箱
        </Text>
        {data ? (
          <Text className="page-footnote__link" onClick={handlePriceChange}>
            改外卖参考价
          </Text>
        ) : null}
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
