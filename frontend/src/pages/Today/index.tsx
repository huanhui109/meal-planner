/**
 * 今日 - 三段式首页: 首屏只做一件事(定这一顿), 次屏才放"决定之后"的事
 *
 * 版式照 《饭决 UI Demo.html》:
 *   ① 状态行「19:20 · 晚餐 · 家里有 6 样」  ← 替代问候语, 餐次由钟点推断不给选
 *   ② 一条浅色出口「不想做饭？点外卖 →」
 *   ③ 决策卡 DecideBoard (.decision = main + aside) ← 全页唯一黑色主按钮
 *   ④ 「家里有啥」快选卡: chip 点一下增/减
 *
 * 次屏(决策之后才关心的事):
 *   ⑤ 补单卡  ⑥ 今晚这一餐  ⑦ 拍照入库页脚
 *   〔折叠〕今日预算条 —— 深夜(22:00-05:00)完全不渲染
 *
 * 判断标准(用来砍模块): 一个模块如果不能帮助用户在 2 秒内定下"这一顿", 它就不该在首页。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Collapse, message } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import { LoadingStack } from '../../components/ui'
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

  const fridgeNames = fridge?.map((item) => item.ingredient_name)
  const expiringCount = fridge?.filter((item) => item.expiring_soon).length ?? null

  return (
    <div className="page">
      {/* ① 状态行: 一行三件事(时间 · 餐次 · 家里有啥), 替代原来的两行问候语 */}
      <HomeStatusBar fridgeCount={fridge?.length ?? null} />

      {loadError && <Alert type="error" showIcon message={loadError} closable />}
      {generation.error && <Alert type="error" showIcon message={generation.error} closable />}

      {/*
        ② 模式出口: 浅色文字链, 不是按钮。
        这个判断用户 1 秒就做完了, 做成带 VS 布局的对比卡是在逼他重做一遍。
        保留出口(它是真实需求), 砍掉对比。
      */}
      {data?.takeout ? (
        <button
          type="button"
          className="text-button takeout-link"
          onClick={() => {
            track('home_takeout_exit', { meal_slot: resolveMealSlot() })
            window.open(data.takeout!.link, '_blank', 'noopener')
          }}
        >
          不想做饭？点外卖 →
        </button>
      ) : null}

      {/*
        ③ 饭决主决策区: 首页唯一主按钮 (Demo 的 .decision 大卡 = main + aside)。
        冰箱名单只用于 aside 的库存命中展示, 拿不到就空着, 不阻塞出菜。
      */}
      <DecideBoard
        fridgeNames={fridgeNames}
        fridgeCount={fridge?.length ?? null}
        expiringCount={expiringCount}
      />

      {/* ④ 「家里有啥」: 次屏第一个, 因为它是"做"这个模式的合法性证明 */}
      <div className="section-label">家里有啥</div>
      <div className="card quick-card">
        <FridgeQuickAdd items={fridge ?? []} onChanged={loadFridge} />
      </div>

      {/* ⑤ 补单决策: 排在决定之后 —— 只有决定了做什么, 才知道缺什么 */}
      {data?.order ? (
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">今晚要补 {data.order.missing_count} 样</div>
              <div className="card-sub">{orderSummaryText(data.order)}</div>
            </div>
            <span className={`tag ${data.order.reaches_min_order ? 'good' : 'warn'}`}>
              {orderStatusText(data.order)}
            </span>
          </div>

          <div className="ingredient-mini">
            {data.order.items.slice(0, 6).map((line) => (
              <div key={`${line.name}-${line.is_topup}`}>
                <span>
                  {line.name}
                  {line.is_topup ? '（凑单）' : ''}
                </span>
                <strong>
                  {formatAmount(line.quantity, line.unit)}
                  {line.estimated_price != null ? ` · ${formatMoney(line.estimated_price)}` : ''}
                </strong>
              </div>
            ))}
          </div>

          {data.order.note && <div className="card-sub" style={{ marginTop: 10 }}>{data.order.note}</div>}

          <div className="decision-actions">
            <button
              type="button"
              className="button primary"
              onClick={() => {
                window.open(data.order!.order_link, '_blank', 'noopener')
              }}
            >
              立即下单
            </button>
            <button type="button" className="text-button" onClick={() => navigate('/menus')}>
              调整菜单
            </button>
          </div>
        </div>
      ) : null}

      {/* ⑥ 今晚这一餐: 决策后的"做完了扣库存"落点 */}
      {data?.tonight ? (
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">{data.tonight.name || '今晚还没定'}</div>
              <div className="card-sub">
                {mealLabel(data.tonight.meal_type)}
                {data.tonight.servings ? ` · ${data.tonight.servings} 人份` : ''}
              </div>
            </div>
            {data.tonight.is_cooked ? (
              <span className="tag good">已做</span>
            ) : data.tonight.is_locked ? (
              <span className="tag">已锁定</span>
            ) : null}
          </div>

          {/* 深夜不出现热量: 说教类信息在深夜是添堵 */}
          {!shouldShowBudgetStrip() ? null : data.tonight.calories != null ? (
            <div className="meal-meta" style={{ marginTop: -4 }}>
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
            <div className="success-line">
              消耗临期食材 {data.tonight.uses_expiring.length} 样：
              {data.tonight.uses_expiring
                .map((item) => `${item.ingredient_name}(${formatRemaining(item.days_left)})`)
                .join(' · ')}
            </div>
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

          <div className="decision-actions">
            {!data.tonight.is_cooked && (
              <button
                type="button"
                className="button primary"
                disabled={cooking}
                onClick={() => void handleCook()}
              >
                {cooking ? '标记中…' : '做完了，扣库存'}
              </button>
            )}
            <button type="button" className="text-button" onClick={() => navigate('/menus')}>
              看整周 / 换一道
            </button>
          </div>
        </div>
      ) : (
        data?.menu_id && (
          <div className="card">
            <div className="empty-state">
              <p>今天没有排餐</p>
              <p className="card-sub" style={{ marginTop: 6 }}>
                这周的菜单里没有今天, 可以去周菜单看看, 或者换一道
              </p>
              <div className="decision-actions" style={{ justifyContent: 'center' }}>
                <button type="button" className="button" onClick={() => navigate('/menus')}>
                  看周菜单
                </button>
              </div>
            </div>
          </div>
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
                  <div className="stat-value" style={{ marginTop: 0 }}>
                    {formatMoney(Math.max(0, budget.remaining_today ?? 0))}
                    <span className="stat-unit">可用 / {formatMoney(dailyBudget)}</span>
                  </div>
                  <div className={`bar ${budgetPercent > 100 ? 'is-over' : ''}`}>
                    <i style={{ width: `${Math.max(0, Math.min(100, budgetPercent))}%` }} />
                  </div>
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
