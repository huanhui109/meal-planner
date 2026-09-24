/**
 * 今日 - 三段式首页: 首屏只做一件事(定这一顿), 次屏才放"决定之后"的事
 *
 * 首屏(不滚动可见, ≤1.5 屏):
 *   ① 状态行「19:20 · 晚餐 · 家里有 6 样」  ← 替代问候语, 餐次由钟点推断不给选
 *   ② 决策区 DecideBoard                    ← 全页唯一黑色主按钮
 *   ③ 一条浅色出口「不想做饭？点外卖 →」
 *
 * 次屏(决策之后才关心的事):
 *   ④ 「家里有啥」摘要条  ⑤ 补单卡  ⑥ 今晚这一餐  ⑦ 拍照入库页脚
 *   〔折叠〕今日预算条 —— 深夜(22:00-05:00)完全不渲染
 *
 * 从首页移走的模块与理由:
 *   - 下一步引导卡:   onboarding 残留。它挡在主按钮下方 = 告诉用户"你还有一步要做",
 *                    直接违反"打开就能定" (本地池 ≥60 道已经保证永远有答案)
 *   - 周概览 4 个磁贴: 旧内核「每周鲜」残留, 每次出现都在制造"我还有一整周要规划"
 *                    的焦虑。移到 /menus 周菜单页, 想看的人会自己去
 *   - 今日流程时间线:  那是**系统**的自动化日志, 不是用户要做的事。移到「我的 → 运行状态」
 *   - 自做 vs 外卖对比卡: 降级成上面 ③ 那一行文字链。能打开饭决的人已经是"愿意做"的人,
 *                    这张卡越强越是在给外卖导流
 *
 * 判断标准(用来砍模块): 一个模块如果不能帮助用户在 2 秒内定下"这一顿", 它就不该在首页。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Collapse, message } from 'antd'
import {
  CheckOutlined,
  DownOutlined,
  ShoppingOutlined,
} from '@ant-design/icons'
import {
  Bar,
  Banner,
  Card,
  Chip,
  EmptyState,
  LoadingStack,
  PillButton,
  SectionTitle,
} from '../../components/ui'
import { getToday } from '../../api/today'
import { markItemCooked, undoMarkCooked } from '../../api/menu'
import { addInventoryItem, listInventory } from '../../api/inventory'
import { useMenuGeneration } from '../../hooks/useMenuGeneration'
import {
  formatAmount,
  formatKcal,
  formatMoney,
  formatPercent,
  formatRemaining,
  mealLabel,
  orderStatusText,
  orderSummaryText,
} from '@shared/index'
import { resolveMealSlot } from '@shared/decide'
import { contextBucket, shouldShowBudgetStrip } from '@shared/decide-context'
import { flushNow, track } from '../../lib/track'
import { useDecideStore } from '../../stores/useDecideStore'
import type { InventoryItem, RecognitionItem, TodayOverview } from '../../types'
import RecognizePanel from '../../components/RecognizePanel'
import DecideBoard from '../../components/DecideBoard'
import HomeStatusBar from '../../components/HomeStatusBar'
import FridgeQuickAdd from '../../components/FridgeQuickAdd'
import { toastWithUndo } from '../../lib/undo'

/**
 * 首页布局版本 —— 埋点用它切片 (R-16)。
 * 值由服务端 /decide 下发后覆盖 lib/layout-version 里的默认值, 拿不到时是 null,
 * 不拿本地猜的值冒充灰度归属 —— 那会让灰度结论直接失效。
 */

/**
 * 首页不再需要 user: 问候语「晚上好, 小明」已经换成状态行, 名字在决策这件事上
 * 没有信息量。props 留空是为了让调用方(App.tsx)不必为一个不再使用的字段取用户信息。
 */
const Today: React.FC = () => {
  const navigate = useNavigate()
  const [data, setData] = useState<TodayOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [cooking, setCooking] = useState(false)
  const [fridge, setFridge] = useState<InventoryItem[] | null>(null)
  const [recognizeOpen, setRecognizeOpen] = useState(false)

  const load = useCallback(async () => {
    setLoadError('')
    try {
      setData(await getToday())
    } catch (error) {
      setLoadError((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadFridge = useCallback(async () => {
    // 冰箱数据拿不到不影响决策, 失败就当"家里有啥"没录过
    try {
      const view = await listInventory()
      setFridge(view.items)
    } catch {
      setFridge(null)
    }
  }, [])

  useEffect(() => {
    void load()
    void loadFridge()
  }, [load, loadFridge])

  /**
   * 首页曝光: session_id 在这里生成(track 内部), 之后同一段过程内所有事件都带它。
   * 只打一次 —— 它是"打开首页"这个事实, 不是"数据刷回来了"这个事实。
   * 所以要等首屏数据落定再打, 否则 has_profile / has_fridge 全是猜的。
   */
  const homeViewSent = useRef(false)
  useEffect(() => {
    if (homeViewSent.current || loading) return
    homeViewSent.current = true
    // layout_version 由 track() 统一补在顶层, 这里不重复传
    track('home_view', {
      meal_slot: resolveMealSlot(),
      bucket: contextBucket(),
      has_profile: data?.ready.has_preferences ?? null,
      has_fridge: (fridge?.length ?? 0) > 0,
      has_last_result: Boolean(useDecideStore.getState().result),
    })
  }, [loading, data, fridge])

  // 关页面前把攒下的埋点发出去, 否则最后一次决策的事件会丢
  useEffect(() => {
    window.addEventListener('pagehide', flushNow)
    return () => window.removeEventListener('pagehide', flushNow)
  }, [])

  const generation = useMenuGeneration(() => {
    message.success('菜单已生成')
    void load()
  })

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
    await loadFridge()
  }

  if (loading) {
    return (
      <div className="page">
        <LoadingStack rows={4} />
      </div>
    )
  }

  const budget = data?.budget
  const dailyBudget = budget?.daily_budget ?? 0
  const spentToday = budget?.spent_today ?? 0
  const budgetPercent = dailyBudget > 0 ? Math.round((spentToday / dailyBudget) * 100) : 0
  // 深夜完全不渲染预算条: 那时候给用户看"预算已用 87%"不是提醒是添堵
  const showBudget = shouldShowBudgetStrip() && dailyBudget > 0

  return (
    <div className="page">
      {/* ① 状态行: 一行三件事(时间 · 餐次 · 家里有啥), 替代原来的两行问候语 */}
      <HomeStatusBar fridgeCount={fridge?.length ?? null} />

      {loadError && <Alert type="error" showIcon message={loadError} closable />}
      {generation.error && <Alert type="error" showIcon message={generation.error} closable />}

      {/*
        ② 饭决主决策区: 首页唯一主按钮。
        放在最上面是因为用户打开 App 的第一诉求就是"今天吃什么",
        其余都是"已经决定之后"才关心的事, 全部下沉。
      */}
      <DecideBoard />

      {/* ③ 模式出口: 浅色文字链, 不是按钮。
          这个判断用户 1 秒就做完了, 做成带 VS 布局的对比卡是在逼他重做一遍。
          保留出口(它是真实需求), 砍掉对比。 */}
      {data?.takeout ? (
        <button
          type="button"
          className="home-takeout-link"
          onClick={() => {
            track('home_takeout_exit', { meal_slot: resolveMealSlot() })
            window.open(data.takeout!.link, '_blank', 'noopener')
          }}
        >
          不想做饭？点外卖 →
        </button>
      ) : null}

      {/* ④ 「家里有啥」: 次屏第一个, 因为它是"做"这个模式的合法性证明 */}
      <SectionTitle>家里有啥</SectionTitle>
      <Card tight>
        <FridgeQuickAdd items={fridge ?? []} onChanged={loadFridge} />
      </Card>

      {/* ⑤ 补单决策: 排在决定之后 —— 只有决定了做什么, 才知道缺什么 */}
      {data?.order ? (
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
      ) : null}

      {/* ⑥ 今晚这一餐: 决策后的"做完了扣库存"落点 */}
      {data?.tonight ? (
        <Card className="tonight-card">
          <div className="card-head">
            <div>
              <div className="card-title">{data.tonight.name || '今晚还没定'}</div>
              <div className="card-sub">
                {mealLabel(data.tonight.meal_type)}
                {data.tonight.servings ? ` · ${data.tonight.servings} 人份` : ''}
              </div>
            </div>
            {data.tonight.is_cooked ? (
              <Chip tone="green">已做</Chip>
            ) : data.tonight.is_locked ? (
              <Chip>已锁定</Chip>
            ) : null}
          </div>

          {/* 深夜不出现热量: 说教类信息在深夜是添堵 */}
          {!shouldShowBudgetStrip() ? null : data.tonight.calories != null ? (
            <div className="meta-row">
              <span>{formatKcal(data.tonight.calories)}</span>
              {data.tonight.protein_g != null && (
                <span>蛋白 {Math.round(data.tonight.protein_g)} g</span>
              )}
              {data.tonight.estimated_cost != null && (
                <span>约 {formatMoney(data.tonight.estimated_cost)}</span>
              )}
            </div>
          ) : null}

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

      {/* 〔折叠〕今日预算条: 单餐预算是事后校验不是事前闸门, 默认收起; 深夜不渲染 */}
      {showBudget && budget ? (
        <Collapse
          ghost
          items={[
            {
              key: 'budget',
              label: `今日预算 · 已用 ${formatPercent(budgetPercent)}`,
              children: (
                <div>
                  <div className="stat-value">
                    {formatMoney(Math.max(0, budget.remaining_today ?? 0))}
                    <span className="stat-unit">可用 / {formatMoney(dailyBudget)}</span>
                  </div>
                  <Bar percent={budgetPercent} tone={budgetPercent > 100 ? 'over' : 'ink'} />
                </div>
              ),
            },
          ]}
        />
      ) : null}

      {/* ⑦ 拍照入库: 页脚文字链, 位置不动 */}
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

export default Today
