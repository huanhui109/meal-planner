/**
 * 偏好设置 - 分组卡片 + 当前值 + 状态点 (参考稿的 set-group/set-row 结构)
 *
 * 五项偏好都做成"点开就地编辑": 一屏能看清哪些填了、哪些还空着,
 * 比跳五个表单页少点很多下。
 */
import { useCallback, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'

import { formatMoney, formatPercent } from '@shared/format'
import type { UserPreferenceSummary } from '@shared/types'

import { Banner, Card, LoadingStack, PageHead, PillButton, SetGroup, SetRow } from '../../components/ui'
import { AutomationCard } from '../../components/automation-card'
import { ChipGroup, NumberField, TextField } from '../../components/ui/form'
import {
  getAutomationStatus,
  getPreferenceSummary,
  logout,
  saveAllergy,
  saveBudget,
  saveDiet,
  saveHealthGoal,
  saveHousehold,
} from '../../lib/api'
import { ensureLogin, toast } from '../../lib/nav'
import { BRAND_HOST } from '../../lib/config'
import { getCachedUser } from '../../lib/session'
import { brand } from '@shared/brand'
import type { AutomationStatus } from '@shared/types'

const CUISINES = ['粤菜', '川菜', '江浙', '湘菜', '鲁菜', '轻食', '日料', '西餐', '东南亚', '东北菜']
const SPICE = ['不吃辣', '微辣', '中辣', '重辣', '变态辣']
const FLAVORS = ['清淡', '偏咸', '偏甜', '酸辣', '酱香']
const STAPLES = ['米饭', '面食', '杂粮', '低碳']
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
  const [summary, setSummary] = useState<UserPreferenceSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState<SectionKey>(null)
  const [saving, setSaving] = useState(false)
  const [automation, setAutomation] = useState<AutomationStatus | null>(null)
  const [automationError, setAutomationError] = useState('')

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
    try {
      await logout()
    } catch {
      /* 退出失败也要清本地 */
    }
    const { clearSession } = await import('../../lib/session')
    clearSession()
    Taro.reLaunch({ url: '/pages/login/index' })
  }

  if (loading) {
    return (
      <View className="page">
        <PageHead title="我的" subtitle="正在读取你的偏好…" />
        <LoadingStack rows={4} />
      </View>
    )
  }

  return (
    <View className="page">
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
        <SetGroup title="家庭与厨房">
          <SetRow
            label="家庭人数 / 每日餐次"
            state={summary?.household ? 'ok' : 'warn'}
            value={
              summary?.household
                ? `${summary.household.member_count} 人 · ${summary.household.meals_per_day} 餐`
                : undefined
            }
            onClick={() => toggle('household')}
          />
          {open === 'household' ? (
            <View style={{ padding: '0 18px 18px' }}>
              <View style={{ display: 'flex', gap: 10 }}>
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
              <View style={{ display: 'flex', gap: 10 }}>
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
        </SetGroup>

        <SetGroup title="口味与安全">
          <SetRow
            label="菜系 / 辣度"
            state={summary?.diet_preference ? 'ok' : 'warn'}
            value={
              summary?.diet_preference
                ? `${summary.diet_preference.cuisines?.slice(0, 2).join('、') || '不限'} · ${SPICE[summary.diet_preference.spice_level] ?? ''}`
                : undefined
            }
            onClick={() => toggle('diet')}
          />
          {open === 'diet' ? (
            <View style={{ padding: '0 18px 18px' }}>
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
            </View>
          ) : null}
        </SetGroup>

        <View className="set-group set-group--cont">
          <SetRow
            label="过敏源 / 忌口"
            state={summary?.allergy_restriction ? 'ok' : 'warn'}
            value={
              summary?.allergy_restriction
                ? summary.allergy_restriction.allergens?.join('、') || '没填过敏源'
                : undefined
            }
            onClick={() => toggle('allergy')}
          />
          {open === 'allergy' ? (
            <View style={{ padding: '0 18px 18px' }}>
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
        </View>

        <SetGroup title="目标与预算">
          <SetRow
            label="目标 / 每日热量"
            state={summary?.health_goal ? 'ok' : 'warn'}
            value={
              summary?.health_goal
                ? `${summary.health_goal.goal_type} · ${Math.round(summary.health_goal.daily_calories)} kcal`
                : undefined
            }
            onClick={() => toggle('health')}
          />
          {open === 'health' ? (
            <View style={{ padding: '0 18px 18px' }}>
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
              <View style={{ display: 'flex', gap: 10 }}>
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
            </View>
          ) : null}
        </SetGroup>

        <View className="set-group set-group--cont">
          <SetRow
            label="每周预算上限"
            state={summary?.budget ? 'ok' : 'warn'}
            value={summary?.budget ? formatMoney(summary.budget.weekly_cap) : undefined}
            onClick={() => toggle('budget')}
          />
          {open === 'budget' ? (
            <View style={{ padding: '0 18px 18px' }}>
              <View style={{ display: 'flex', gap: 10 }}>
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
        </View>
      </View>

      <AutomationCard status={automation} error={automationError} />

      <View className="page-footnote">
        {brand.localDataNote}
        {'\n'}
        当前部署: {BRAND_HOST}
      </View>

      <View style={{ marginTop: 18 }}>
        <PillButton variant="ghost" block onClick={handleLogout}>
          退出登录
        </PillButton>
      </View>

      <View style={{ height: 24 }} />
    </View>
  )
}
