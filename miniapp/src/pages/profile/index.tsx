/**
 * 偏好设置 - 分组卡片 + 当前值 + 状态点 (参考稿的 set-group/set-row 结构)
 *
 * 五项偏好都做成"点开就地编辑": 一屏能看清哪些填了、哪些还空着,
 * 比跳五个表单页少点很多下。
 */
import { useCallback, useState } from 'react'
import { Switch, Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh } from '@tarojs/taro'

import { currentWeekStart, formatMoney, formatPercent } from '@shared/format'
import { GUIDE_SHOW_MODE_LABELS } from '@shared/user-settings'
import type { GuideShowMode } from '@shared/user-settings'
import type { UserPreferenceSummary } from '@shared/types'

import { Banner, Card, cx, LoadingStack, PageHead, PillButton, SetGroup, SetRow } from '../../components/ui'
import { AutomationCard } from '../../components/automation-card'
import { FeedbackSheet } from '../../components/feedback-sheet'
import { openCustomerServiceChat } from '../../lib/customer-service'
import { track } from '../../lib/events'
import { ChipGroup, NumberField, TextField } from '../../components/ui/form'
import {
  getAutomationStatus,
  getPreferenceSummary,
  logout,
  saveAllergy,
  saveBudget,
  saveDiet,
  rebuildFromFridge,
  saveHealthGoal,
  saveHousehold,
} from '../../lib/api'
import { ensureLogin, toast } from '../../lib/nav'
import { px } from '../../lib/px'
import { BRAND_HOST } from '../../lib/config'
import { getCachedUser } from '../../lib/session'
import { useTheme, useThemeClass } from '../../lib/theme'
import { useUserSettings } from '../../lib/user-settings'
import { brand } from '@shared/brand'
import type { AutomationStatus } from '@shared/types'

const CUISINES = ['粤菜', '川菜', '江浙', '湘菜', '鲁菜', '轻食', '日料', '西餐', '东南亚', '东北菜']
const SPICE = ['不吃辣', '微辣', '中辣', '重辣', '变态辣']
const FLAVORS = ['清淡', '偏咸', '偏甜', '酸辣', '酱香']
const STAPLES = ['米饭', '面食', '杂粮', '低碳']
/** Switch 打开时的颜色: 用语义绿, 与 Chip--accent / 状态点一致 */
const SWITCH_COLOR = '#34c759'
const GOALS = ['减脂', '增肌', '控糖', '控压', '维持']
const EQUIPMENTS = ['灶台', '蒸锅', '空气炸锅', '微波炉', '烤箱', '电饭煲', '压力锅', '破壁机', '电磁炉', '榨汁机']

type SectionKey = 'household' | 'diet' | 'allergy' | 'health' | 'budget' | null

interface HouseholdForm {
  member_count: number
  meals_per_day: number
  kitchen_equipments: string[]
  weekday_cook_minutes: number
  weekend_cook_minutes: number
}

interface DietForm {
  cuisines: string[]
  spice_level: number
  flavor_preference: string
  staple_preference: string
}

interface AllergyForm {
  allergens: string[]
  avoid_ingredients: string[]
  dietary_restrictions: string
}

interface HealthForm {
  goal_type: string
  daily_calories: number
  protein_pct: number
  carb_pct: number
  fat_pct: number
}

interface BudgetForm {
  weekday_daily_budget: number
  weekend_daily_budget: number
  weekly_cap: number
  min_meal_budget: number
  /** 一顿外卖的参考价, 今日页的「自做 vs 外卖」按它估算 */
  takeout_reference_price: number
}

const DEFAULT_HOUSEHOLD: HouseholdForm = {
  member_count: 1,
  meals_per_day: 2,
  kitchen_equipments: ['灶台'],
  weekday_cook_minutes: 30,
  weekend_cook_minutes: 60,
}

export default function ProfilePage() {
  const themeClass = useThemeClass()
  const [summary, setSummary] = useState<UserPreferenceSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState<SectionKey>(null)
  const [saving, setSaving] = useState(false)
  const [automation, setAutomation] = useState<AutomationStatus | null>(null)
  const [automationError, setAutomationError] = useState('')
  const [subscribeStats, setSubscribeStats] = useState({
    hasAccepted: false,
    hasDeclined: false,
  })
  const [subscribing, setSubscribing] = useState(false)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)

  /** 按冰箱重排本周: 会改掉未锁定的餐次, 所以先确认一次 */
  const handleFridgeRebuild = useCallback(async () => {
    if (rebuilding) return
    let go = false
    try {
      const ask = await Taro.showModal({
        title: '按冰箱重排本周',
        content: '本周未锁定的餐次会换成"用冰箱现有食材最做得出来"的菜, 锁定的餐次保持不动。',
        confirmText: '重排',
        cancelText: '再想想',
      })
      go = Boolean(ask.confirm)
    } catch {
      return // 用户取消
    }
    if (!go) return

    setRebuilding(true)
    Taro.showLoading({ title: '正在重排…', mask: true })
    try {
      const payload = await rebuildFromFridge(currentWeekStart())
      Taro.hideLoading()
      const { cookable_now: cookable, need_shopping: need, changed_items: changed } = payload.summary
      const answer = await Taro.showModal({
        title: '重排完成',
        content: `换了 ${changed} 餐, 其中 ${cookable} 餐冰箱现有食材就能做, ${need} 餐还要补货。`,
        confirmText: '看采购清单',
        cancelText: '知道了',
      })
      if (answer.confirm) Taro.switchTab({ url: '/pages/shopping/index' })
    } catch (error: unknown) {
      toast((error as Error).message || '重排失败, 请稍后再试')
    } finally {
      Taro.hideLoading()
      setRebuilding(false)
    }
  }, [rebuilding])

  const [household, setHousehold] = useState<HouseholdForm>(DEFAULT_HOUSEHOLD)
  const [diet, setDiet] = useState<DietForm>({
    cuisines: [],
    spice_level: 1,
    flavor_preference: '清淡',
    staple_preference: '米饭',
  })
  const [allergy, setAllergy] = useState<AllergyForm>({
    allergens: [],
    avoid_ingredients: [],
    dietary_restrictions: '',
  })
  const [health, setHealth] = useState<HealthForm>({
    goal_type: '维持',
    daily_calories: 1800,
    protein_pct: 30,
    carb_pct: 40,
    fat_pct: 30,
  })
  const [budget, setBudget] = useState<BudgetForm>({
    weekday_daily_budget: 35,
    weekend_daily_budget: 80,
    weekly_cap: 350,
    min_meal_budget: 8,
    takeout_reference_price: 26,
  })

  const user = getCachedUser()
  const [theme, setTheme] = useTheme()
  const [settings, updateGuide] = useUserSettings()
  const guide = settings.guide

  const load = useCallback(async () => {
    if (!ensureLogin()) return
    try {
      const data = await getPreferenceSummary()
      setSummary(data)
      if (data.household) {
        setHousehold({
          member_count: data.household.member_count,
          meals_per_day: data.household.meals_per_day,
          kitchen_equipments: data.household.kitchen_equipments ?? [],
          weekday_cook_minutes: data.household.weekday_cook_minutes,
          weekend_cook_minutes: data.household.weekend_cook_minutes,
        })
      }
      if (data.diet_preference) {
        setDiet({
          cuisines: data.diet_preference.cuisines ?? [],
          spice_level: data.diet_preference.spice_level,
          flavor_preference: data.diet_preference.flavor_preference,
          staple_preference: data.diet_preference.staple_preference,
        })
      }
      if (data.allergy_restriction) {
        setAllergy({
          allergens: data.allergy_restriction.allergens ?? [],
          avoid_ingredients: data.allergy_restriction.avoid_ingredients ?? [],
          dietary_restrictions: data.allergy_restriction.dietary_restrictions || '',
        })
      }
      if (data.health_goal) {
        setHealth({
          goal_type: data.health_goal.goal_type || '维持',
          daily_calories: data.health_goal.daily_calories,
          protein_pct: data.health_goal.protein_pct,
          carb_pct: data.health_goal.carb_pct,
          fat_pct: data.health_goal.fat_pct,
        })
      }
      if (data.budget) {
        setBudget({
          weekday_daily_budget: data.budget.weekday_daily_budget,
          weekend_daily_budget: data.budget.weekend_daily_budget,
          weekly_cap: data.budget.weekly_cap || 350,
          min_meal_budget: data.budget.min_meal_budget ?? 8,
          takeout_reference_price: data.budget.takeout_reference_price ?? 26,
        })
      }
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setLoading(false)
      // 下拉刷新必须在这里收尾: 成功失败都要停, 否则动画一直转
      Taro.stopPullDownRefresh()
    }
    try {
      setAutomation(await getAutomationStatus())
    } catch (err) {
      setAutomationError((err as Error).message)
    }
  }, [])

  useDidShow(() => {
    // 「我的」已经不是 tab 页了 (4 Tab 之外), 所以不调 syncTabBar
    void load()
  })

  // config 里开了 enablePullDownRefresh, 这里必须接住并收尾 —— 否则下拉的 loading
  // 动画永远停不下来 (之前整页找不到 stopPullDownRefresh, 只能杀进程)
  usePullDownRefresh(() => {
    void load()
  })

  const toggle = (key: SectionKey) => setOpen((prev) => (prev === key ? null : key))

  const save = async (key: Exclude<SectionKey, null>, payload: Record<string, unknown>) => {
    setSaving(true)
    try {
      if (key === 'household') await saveHousehold(payload)
      if (key === 'diet') await saveDiet(payload)
      if (key === 'allergy') await saveAllergy(payload)
      if (key === 'health') await saveHealthGoal(payload)
      if (key === 'budget') await saveBudget(payload)
      toast('已保存', 'success')
      setOpen(null)
      await load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const toggleIn = <T extends string>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((item) => item !== value) : [...list, value]

  const doneCount = summary
    ? [summary.household, summary.diet_preference, summary.allergy_restriction, summary.health_goal, summary.budget].filter(
        Boolean,
      ).length
    : 0

  const handleLogout = async () => {
    const modal = await Taro.showModal({ title: '退出登录', content: '确认退出当前账号?' })
    if (!modal.confirm) return
    track('logout')
    try {
      await logout()
    } catch {
      /* 退出失败也要清本地 */
    }
    const { clearSession } = await import('../../lib/session')
    clearSession()
    Taro.reLaunch({ url: '/pages/login/index' })
  }

  const openSubscribeSheet = async () => {
    setSubscribing(true)
    try {
      const { ensureLogin } = await import('../../lib/nav')
      if (!ensureLogin()) return
      const { getSubscribeTemplates, getSubscribeStatus } = await import('../../lib/api')
      const { requestSubscribe } = await import('../../lib/subscribe')
      const { items } = await getSubscribeTemplates()
      // 看用户已有授权状态
      const statuses = await Promise.all(
        items.map(async (t) => {
          try {
            return await getSubscribeStatus(t.template_id)
          } catch {
            return null
          }
        }),
      )
      const grantedCount = statuses.filter((s) => s?.granted).length
      const declinedCount = statuses.filter((s) => s && !s.granted).length
      setSubscribeStats({
        hasAccepted: grantedCount > 0,
        hasDeclined: declinedCount > 0 && grantedCount === 0,
      })

      const choices = items.map((t, i) => ({
        id: t.template_id,
        title: `${t.title}（${t.persistent ? '长期' : '一次性'}）`,
        desc: t.description,
        grant: statuses[i]?.granted ?? false,
      }))

      const idsToAsk = choices.filter((c) => !c.grant).map((c) => c.id)
      if (idsToAsk.length === 0) {
        await Taro.showModal({ title: '已全部订阅', content: '后续菜单 / 临期 / 库存提醒都会推送给您', showCancel: false })
        return
      }
      const decisions = await requestSubscribe({ tmplIds: idsToAsk.slice(0, 3) })
      // 重新拉一次状态更新 UI
      const refreshed = await Promise.all(
        items.map(async (t) => {
          try {
            return await getSubscribeStatus(t.template_id)
          } catch {
            return null
          }
        }),
      )
      const newGranted = refreshed.filter((s) => s?.granted).length
      setSubscribeStats({
        hasAccepted: newGranted > 0,
        hasDeclined: refreshed.every((s) => s && !s.granted) && refreshed.length > 0,
      })
      const acceptedIds = idsToAsk.filter((id) => decisions[id] === 'accept')
      if (acceptedIds.length > 0) {
        await Taro.showToast({ title: `已开通 ${acceptedIds.length} 项`, icon: 'success' })
      }
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '加载失败', icon: 'none' })
    } finally {
      setSubscribing(false)
    }
  }
  if (loading) {
    return (
      <View className={`page ${themeClass}`}>
        <PageHead title="我的" subtitle="正在读取你的偏好…" />
        <LoadingStack rows={4} />
      </View>
    )
  }

  return (
    <View className={`page ${themeClass}`}>
      <PageHead
        title="我的"
        subtitle={
          doneCount === 5
            ? '五项都填好了, 生成的菜单会更合口味'
            : `还差 ${5 - doneCount} 项没填, 填得越全菜单越准`
        }
      />

      <Card>
        <View className="card__head">
          <View>
            <Text className="card__label">当前登录</Text>
            <View className="meal__name" style={{ marginTop: 4 }}>
              {user?.name || '微信用户'}
            </View>
          </View>
          <Text className="chip">{user?.open_id?.startsWith('wechat:') ? '微信' : '飞书'}</Text>
        </View>
      </Card>

      {doneCount < 5 ? (
        <Banner tone="warn">先填「家庭与厨房」和「预算」这两项, 就能生成一份靠谱的菜单了。</Banner>
      ) : null}

      <View style={{ marginTop: 14 }}>
        <SetGroup title="冰箱">
          <SetRow
            label="按冰箱重排本周"
            value={rebuilding ? '重排中…' : '先把现有食材排进菜单, 再算采购清单'}
            onClick={handleFridgeRebuild}
          />
        </SetGroup>
      </View>

      {/* Demo 偏好卡: 4 个 setting-row, 点开就地编辑 (表单逻辑不变) */}
      <View className="d-card" style={{ marginTop: 14 }}>
        <View className="d-setting-row tap" onClick={() => toggle('household')}>
          <View className="d-setting-icon">
            <Text>{summary?.household?.member_count ?? '家'}</Text>
          </View>
          <View className="d-setting-copy">
            <Text className="d-setting-copy__title">家庭与厨房</Text>
            <View className="d-setting-copy__sub">
              {summary?.household
                ? `${summary.household.member_count} 人 · ${summary.household.kitchen_equipments?.slice(0, 3).join(' / ') || '设备未填'}`
                : '还没设置'}
            </View>
          </View>
          <Text className="d-setting-value">{summary?.household ? '已设置 ›' : '去设置 ›'}</Text>
        </View>
        {open === 'household' ? (
          <View style={{ padding: '10px 0 4px' }}>
              <View style={{ display: 'flex', gap: px(10) }}>
                <NumberField
                  label="家庭人数"
                  value={household.member_count}
                  style={{ flex: 1 }}
                  onChange={(value) => setHousehold((prev) => ({ ...prev, member_count: value || 1 }))}
                />
                <NumberField
                  label="每日餐次"
                  value={household.meals_per_day}
                  style={{ flex: 1 }}
                  onChange={(value) => setHousehold((prev) => ({ ...prev, meals_per_day: value || 2 }))}
                />
              </View>
              <ChipGroup
                label="厨房设备"
                hint="没有的设备不会排进菜单"
                options={EQUIPMENTS}
                selected={household.kitchen_equipments}
                onToggle={(value) =>
                  setHousehold((prev) => ({
                    ...prev,
                    kitchen_equipments: toggleIn(prev.kitchen_equipments, value),
                  }))
                }
              />
              <View style={{ display: 'flex', gap: px(10) }}>
                <NumberField
                  label="工作日做饭 (分钟)"
                  value={household.weekday_cook_minutes}
                  style={{ flex: 1 }}
                  onChange={(value) =>
                    setHousehold((prev) => ({ ...prev, weekday_cook_minutes: value || 30 }))
                  }
                />
                <NumberField
                  label="周末做饭 (分钟)"
                  value={household.weekend_cook_minutes}
                  style={{ flex: 1 }}
                  onChange={(value) =>
                    setHousehold((prev) => ({ ...prev, weekend_cook_minutes: value || 60 }))
                  }
                />
              </View>
              <View style={{ marginTop: 16 }}>
                <PillButton block disabled={saving} onClick={() => save('household', { ...household })}>
                  {saving ? '保存中…' : '保存家庭信息'}
                </PillButton>
              </View>
            </View>
          ) : null}

        <View className="d-setting-row tap" onClick={() => toggle('diet')}>
          <View className="d-setting-icon">
            <Text>味</Text>
          </View>
          <View className="d-setting-copy">
            <Text className="d-setting-copy__title">口味与忌口</Text>
            <View className="d-setting-copy__sub">
              {summary?.diet_preference
                ? `${summary.diet_preference.flavor_preference || '不限'} · ${SPICE[summary.diet_preference.spice_level] ?? ''}${
                    summary?.allergy_restriction?.allergens?.length
                      ? ` · 忌口 ${summary.allergy_restriction.allergens.slice(0, 2).join('、')}`
                      : ''
                  }`
                : '还没设置'}
            </View>
          </View>
          <Text className="d-setting-value">
            {summary?.diet_preference || summary?.allergy_restriction ? '已设置 ›' : '去设置 ›'}
          </Text>
        </View>
        {open === 'diet' ? (
          <View style={{ padding: '10px 0 4px' }}>
              <ChipGroup
                label="偏好菜系"
                hint="可多选, 不选则由 AI 自由搭配"
                options={CUISINES}
                selected={diet.cuisines}
                onToggle={(value) => setDiet((prev) => ({ ...prev, cuisines: toggleIn(prev.cuisines, value) }))}
              />
              <ChipGroup
                label="辣度"
                options={SPICE}
                multiple={false}
                selected={[SPICE[diet.spice_level] ?? SPICE[0]]}
                onChange={(value) =>
                  setDiet((prev) => ({ ...prev, spice_level: SPICE.indexOf(value) }))
                }
              />
              <ChipGroup
                label="口味偏好"
                options={FLAVORS}
                multiple={false}
                selected={[diet.flavor_preference]}
                onChange={(value) => setDiet((prev) => ({ ...prev, flavor_preference: value }))}
              />
              <ChipGroup
                label="主食偏好"
                options={STAPLES}
                multiple={false}
                selected={[diet.staple_preference]}
                onChange={(value) => setDiet((prev) => ({ ...prev, staple_preference: value }))}
              />
              <View style={{ marginTop: 16 }}>
                <PillButton block disabled={saving} onClick={() => save('diet', { ...diet })}>
                  {saving ? '保存中…' : '保存口味'}
                </PillButton>
              </View>

              <View style={{ height: 18 }} />
              <TextField
                label="过敏源 (用顿号或逗号分隔)"
                hint="绝对禁止出现, 例如: 花生、芒果、虾"
                value={allergy.allergens.join('、')}
                placeholder="花生、芒果"
                onChange={(value) =>
                  setAllergy((prev) => ({
                    ...prev,
                    allergens: value
                      .split(/[、,，\s]+/)
                      .map((item) => item.trim())
                      .filter(Boolean),
                  }))
                }
              />
              <TextField
                label="忌口食材"
                hint="尽量避免, 例如: 香菜、动物内脏"
                value={allergy.avoid_ingredients.join('、')}
                placeholder="香菜"
                onChange={(value) =>
                  setAllergy((prev) => ({
                    ...prev,
                    avoid_ingredients: value
                      .split(/[、,，\s]+/)
                      .map((item) => item.trim())
                      .filter(Boolean),
                  }))
                }
              />
              <TextField
                label="饮食习惯"
                hint="例如: 清真、素食、不吃牛肉"
                value={allergy.dietary_restrictions}
                onChange={(value) => setAllergy((prev) => ({ ...prev, dietary_restrictions: value }))}
              />
              <View style={{ marginTop: 16 }}>
                <PillButton block disabled={saving} onClick={() => save('allergy', { ...allergy })}>
                  {saving ? '保存中…' : '保存忌口'}
                </PillButton>
              </View>
            </View>
          ) : null}

        <View className="d-setting-row tap" onClick={() => toggle('health')}>
          <View className="d-setting-icon">
            <Text>衡</Text>
          </View>
          <View className="d-setting-copy">
            <Text className="d-setting-copy__title">目标与预算</Text>
            <View className="d-setting-copy__sub">
              {summary?.health_goal || summary?.budget
                ? `${summary?.health_goal?.goal_type || '维持'} · 工作日 ${formatMoney(
                    summary?.budget?.weekday_daily_budget ?? 0,
                  )} / 天`
                : '还没设置'}
            </View>
          </View>
          <Text className="d-setting-value">
            {summary?.health_goal || summary?.budget ? '已设置 ›' : '去设置 ›'}
          </Text>
        </View>
        {open === 'health' ? (
          <View style={{ padding: '10px 0 4px' }}>
              <ChipGroup
                label="目标类型"
                options={GOALS}
                multiple={false}
                selected={[health.goal_type]}
                onChange={(value) => setHealth((prev) => ({ ...prev, goal_type: value }))}
              />
              <NumberField
                label="每日目标热量 (千卡)"
                value={health.daily_calories}
                onChange={(value) => setHealth((prev) => ({ ...prev, daily_calories: value || 1800 }))}
              />
              <View style={{ display: 'flex', gap: px(10) }}>
                <NumberField
                  label="蛋白 %"
                  value={health.protein_pct}
                  style={{ flex: 1 }}
                  onChange={(value) => setHealth((prev) => ({ ...prev, protein_pct: value || 0 }))}
                />
                <NumberField
                  label="碳水 %"
                  value={health.carb_pct}
                  style={{ flex: 1 }}
                  onChange={(value) => setHealth((prev) => ({ ...prev, carb_pct: value || 0 }))}
                />
                <NumberField
                  label="脂肪 %"
                  value={health.fat_pct}
                  style={{ flex: 1 }}
                  onChange={(value) => setHealth((prev) => ({ ...prev, fat_pct: value || 0 }))}
                />
              </View>
              <View className="card__hint" style={{ marginTop: 8 }}>
                三项加起来是 {formatPercent(health.protein_pct + health.carb_pct + health.fat_pct)}, 建议凑满 100%。
              </View>
              <View style={{ marginTop: 16 }}>
                <PillButton block disabled={saving} onClick={() => save('health', { ...health })}>
                  {saving ? '保存中…' : '保存健康目标'}
                </PillButton>
              </View>

              <View style={{ height: 18 }} />
              <View style={{ display: 'flex', gap: px(10) }}>
                <NumberField
                  label="工作日每日 (元)"
                  value={budget.weekday_daily_budget}
                  style={{ flex: 1 }}
                  onChange={(value) =>
                    setBudget((prev) => ({ ...prev, weekday_daily_budget: value || 35 }))
                  }
                />
                <NumberField
                  label="周末每日 (元)"
                  value={budget.weekend_daily_budget}
                  style={{ flex: 1 }}
                  onChange={(value) =>
                    setBudget((prev) => ({ ...prev, weekend_daily_budget: value || 80 }))
                  }
                />
              </View>
              <NumberField
                label="每周上限 (元)"
                value={budget.weekly_cap}
                onChange={(value) => setBudget((prev) => ({ ...prev, weekly_cap: value }))}
              />
              <NumberField
                label="单餐下限 (元)"
                hint="低于这个金额的一餐会被提示, 避免只吃主食"
                value={budget.min_meal_budget}
                onChange={(value) => setBudget((prev) => ({ ...prev, min_meal_budget: value }))}
              />
              <NumberField
                label="一顿外卖参考价 (元)"
                hint="今日页的「自做 vs 外卖」按它估算; 在卡片上改价也会写回这里"
                value={budget.takeout_reference_price}
                onChange={(value) =>
                  setBudget((prev) => ({ ...prev, takeout_reference_price: value }))
                }
              />
              <View style={{ marginTop: 16 }}>
                <PillButton block disabled={saving} onClick={() => save('budget', { ...budget })}>
                  {saving ? '保存中…' : '保存预算'}
                </PillButton>
              </View>
            </View>
          ) : null}

        {/* 推荐顺序由决策引擎固定, 这里只解释 + 入口到 3 题偏好重答 */}
        <View
          className="d-setting-row tap"
          onClick={() => Taro.navigateTo({ url: '/pages/onboarding/index?from=profile' })}
        >
          <View className="d-setting-icon">
            <Text>序</Text>
          </View>
          <View className="d-setting-copy">
            <Text className="d-setting-copy__title">推荐顺序</Text>
            <View className="d-setting-copy__sub">临期优先 → 库存命中 → 最近少吃</View>
          </View>
          <Text className="d-setting-value">调整 ›</Text>
        </View>
      </View>

      <AutomationCard status={automation} error={automationError} />

      {/* 引导不再是写死的"没走过就必须看", 开关和展示时机都交给用户 (shared/user-settings.ts) */}
      <View style={{ marginTop: 14 }}>
        <SetGroup title="用户信息">
          <SetRow
            label="新手指引"
            control={
              <Switch
                checked={guide.enabled}
                color={SWITCH_COLOR}
                onChange={(event) => updateGuide({ enabled: event.detail.value })}
              />
            }
          />
          {guide.enabled ? (
            <>
              <SetRow
                label="展示时机"
                value={GUIDE_SHOW_MODE_LABELS[guide.showMode]}
                onClick={() => {
                  const order: GuideShowMode[] = ['once', 'always', 'never']
                  const next = order[(order.indexOf(guide.showMode) + 1) % order.length]
                  updateGuide({ showMode: next })
                  toast(`新手指引: ${GUIDE_SHOW_MODE_LABELS[next]}`)
                }}
              />
              <SetRow
                label="重新查看引导"
                value={guide.completed ? '已看过' : '未看完'}
                state={guide.completed ? 'ok' : 'warn'}
                onClick={() => Taro.navigateTo({ url: '/pages/onboarding/index' })}
              />
            </>
          ) : null}
        </SetGroup>
      </View>

      <View className="d-section-label">外观</View>
      <View className="d-card">
        <View className="d-card-title">跟随你的使用环境</View>
        <View className="d-card-sub">自动会跟随系统的明暗模式</View>
        <View className="d-theme-row">
          <View
            className={`d-theme-choice tap${theme === 'auto' ? ' d-theme-choice--active' : ''}`}
            onClick={() => setTheme('auto')}
          >
            <Text>自动</Text>
          </View>
          <View
            className={`d-theme-choice tap${theme === 'cream' ? ' d-theme-choice--active' : ''}`}
            onClick={() => setTheme('cream')}
          >
            <Text>明亮</Text>
          </View>
          <View
            className={`d-theme-choice tap${theme === 'dark' ? ' d-theme-choice--active' : ''}`}
            onClick={() => setTheme('dark')}
          >
            <Text>深色</Text>
          </View>
        </View>
      </View>

      <View className="page-footnote">
        {brand.localDataNote}
        {'\n'}
        当前部署: {BRAND_HOST}
      </View>

      <View style={{ marginTop: 14 }}>
        <SetGroup title="更多">
          <SetRow
            label="邀请好友"
            value="得 AI 额度"
            onClick={() => Taro.navigateTo({ url: '/pages/invite/index' })}
          />
          <SetRow
            label="历史菜单"
            value="查看"
            onClick={() => Taro.navigateTo({ url: '/pages/menu-history/index' })}
          />
        </SetGroup>
      </View>

      <View style={{ marginTop: 14 }}>
        <SetGroup title="通知">
          <SetRow
            label="消息订阅"
            value={subscribing ? '加载中…' : '管理'}
            onClick={openSubscribeSheet}
            state={subscribeStats.hasAccepted ? 'ok' : subscribeStats.hasDeclined ? 'warn' : 'none'}
          />
        </SetGroup>
      </View>

      <View style={{ marginTop: 14 }}>
        <SetGroup title="关于">
          <SetRow
            label={`关于${brand.name}`}
            value="查看"
            onClick={() => Taro.navigateTo({ url: '/pages/about/index' })}
          />
          <SetRow label="意见反馈" value="提交" onClick={() => setFeedbackOpen(true)} />
          <SetRow
            label="在线客服"
            value="咨询"
            onClick={() => {
              void openCustomerServiceChat(() =>
                Taro.showToast({ title: '请到「我的 → 意见反馈」留言', icon: 'none', duration: 2500 }),
              )
            }}
          />
        </SetGroup>
      </View>

      <View style={{ marginTop: 18 }}>
        <PillButton variant="ghost" block onClick={handleLogout}>
          退出登录
        </PillButton>
      </View>

      <View style={{ height: 24 }} />

      <FeedbackSheet open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
    </View>
  )
}
