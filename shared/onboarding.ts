/**
 * 饭决 Onboarding 题库 (需求 1: ≤60 秒; 需求 8: 一次设置长期生效)
 *
 * 三问三屏, 每屏 1 次点选, 每屏都能跳过 —— 引导的目的是"尽快吃到第一个结果",
 * 不是"采集完整档案"。用户没耐心填的表, 价值等于零。
 *
 * 时间预算: Q1 8s + Q2 15s + Q3 8s + 出结果 1.5s ≈ 45 秒
 *
 * 题库放在 shared 是因为 H5 与小程序必须问一样的问题、写一样的字段,
 * 否则"我在小程序设的口味, 打开 H5 变了" 会直接毁掉信任。
 */
import type { MealSlot } from './types'

export type OnboardingKey = 'flavor' | 'avoid' | 'time'

export interface OnboardingOption {
  value: string
  label: string
  hint?: string
}

export interface OnboardingQuestion {
  key: OnboardingKey
  /** 屏上的问题, 用口语, 别写"请选择您的口味偏好" */
  title: string
  subtitle: string
  /** true = 可多选; false = 单选(点了就进下一屏, 更快) */
  multiple: boolean
  options: OnboardingOption[]
  /** 「没啥忌口 / 都行」这类跳过项, 点了等于本屏不选 */
  skipLabel?: string
}

export const ONBOARDING_QUESTIONS: OnboardingQuestion[] = [
  {
    key: 'flavor',
    title: '你大概是哪种口味？',
    subtitle: '选一个最接近的，之后随时能改',
    multiple: false,
    options: [
      { value: 'spicy', label: '无辣不欢', hint: '川湘、重口味' },
      { value: 'light', label: '清淡为主', hint: '蒸煮、少油少盐' },
      { value: 'sour_sweet', label: '酸甜口', hint: '糖醋、番茄' },
      { value: 'any', label: '什么都行', hint: '让饭决自由发挥' },
    ],
  },
  {
    key: 'avoid',
    title: '有忌口吗？',
    subtitle: '没有就直接跳过，不用凑',
    multiple: true,
    options: [
      { value: '香菜', label: '香菜' },
      { value: '内脏', label: '内脏' },
      { value: '海鲜', label: '海鲜' },
      { value: '羊肉', label: '羊肉' },
      { value: '猪肉', label: '猪肉' },
      { value: '辛辣', label: '辛辣' },
    ],
    skipLabel: '没啥忌口',
  },
  {
    key: 'time',
    title: '做饭多久你能接受？',
    subtitle: '决定给你推快手菜还是硬菜',
    multiple: false,
    options: [
      { value: 'quick', label: '15 分钟快手', hint: '越快越好' },
      { value: 'normal', label: '半小时', hint: '正常做一顿' },
      { value: 'slow', label: '愿意炖一小时', hint: '周末有空' },
      { value: 'takeout', label: '我常点外卖', hint: '多给点外卖建议' },
    ],
  },
]

export const ONBOARDING_TOTAL = ONBOARDING_QUESTIONS.length

/** Q1 口味 → 辣度 + 口味倾向 + 菜系 */
const FLAVOR_MAP: Record<string, { spice: number; flavor: string; cuisines: string[] }> = {
  spicy: { spice: 4, flavor: '重辣', cuisines: ['川湘'] },
  light: { spice: 0, flavor: '清淡', cuisines: ['粤式', '轻食'] },
  sour_sweet: { spice: 1, flavor: '酸甜', cuisines: ['江浙'] },
  any: { spice: 2, flavor: '不挑', cuisines: ['家常'] },
}

/** Q3 时间预算 → 工作日做饭时长(分钟) + 场景标签 */
const TIME_MAP: Record<string, { minutes: number; scene: string }> = {
  quick: { minutes: 15, scene: '快手' },
  normal: { minutes: 30, scene: '在家做' },
  slow: { minutes: 90, scene: '愿意炖一小时' },
  takeout: { minutes: 30, scene: '常点外卖' },
}

export type OnboardingAnswers = Partial<Record<OnboardingKey, string[]>>

/**
 * 答案 → 后端偏好载荷。
 * 未答的题用默认值补齐, 保证后端的 diet/allergy/household 三条记录一定写得进去 ——
 * 档案缺失会让决策引擎退化为"什么都推", 那是比推错更糟的体验。
 */
export function toPreferencePayload(answers: OnboardingAnswers) {
  const flavorKey = answers.flavor?.[0] || 'any'
  const flavor = FLAVOR_MAP[flavorKey] ?? FLAVOR_MAP.any
  const timeKey = answers.time?.[0] || 'normal'
  const time = TIME_MAP[timeKey] ?? TIME_MAP.normal
  const avoid = answers.avoid ?? []

  return {
    diet: {
      cuisines: flavor.cuisines,
      spice_level: flavor.spice,
      flavor_preference: flavor.flavor,
      staple_preference: '米饭',
      scene_tags: [time.scene],
    },
    allergy: {
      allergens: [],
      avoid_ingredients: avoid,
      dietary_restrictions: '',
    },
    household: {
      member_count: 2,
      meals_per_day: 3,
      kitchen_equipments: [],
      weekday_cook_minutes: time.minutes,
      weekend_cook_minutes: time.minutes,
    },
  }
}

/** 引导完成后的第一屏文案 —— 直接给结果, 不要"设置成功"这种废话 */
export function onboardingGreeting(slot: MealSlot): string {
  if (slot === 'late_night') return '这么晚了，吃点轻的'
  if (slot === 'breakfast') return '早上好，今天吃这个'
  if (slot === 'lunch') return '午饭有着落了'
  return '今晚就这个，别纠结了'
}
