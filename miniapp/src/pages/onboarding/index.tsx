/**
 * 饭决引导 (需求 1: ≤60 秒)
 *
 * 3 问 3 屏, 每屏 1 次点选, 每屏都能跳过。题库与答案映射全部来自
 * shared/onboarding.ts —— H5 与小程序必须问一样的问题、写一样的字段。
 *
 * 与旧版最大的区别: **答完立刻出结果**。
 * 旧版走完引导还要等 1-2 分钟生成周菜单才看到东西, 那是"被决定的爽感"的断点。
 * 现在答完第 3 题就在引导页里给出第一张结果卡, 用户还没进首页就已经吃过一次甜头。
 *
 * V1.1 体验升级 (参考苹果新装 iOS 指引): 开场 Logo 初始化动效 + 7 点依次点亮、
 * 分段进度条、每题进出场过渡、选项选中态强化。
 *
 * ⚠ 偏好必须真的落库 (P0 老问题): 早期版本只 setOnboarded(true) 就把草稿删了,
 *   用户在引导里选的东西从来没提交过, 进首页又被要求"去填偏好", 引导等于白做。
 *   现在直接 PUT 三条偏好; 失败也要继续 —— 引导的目的是尽快吃到第一个答案。
 */
import { useEffect, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import {
  ONBOARDING_QUESTIONS,
  ONBOARDING_TOTAL,
  onboardingGreeting,
  toPreferencePayload,
  type OnboardingAnswers,
  type OnboardingKey,
} from '@shared/onboarding'
import { resolveMealSlot } from '@shared/decide'
import { brand } from '@shared/brand'
import { formatMinutes } from '@shared/format'

import { PillButton } from '../../components/ui'
import { LogoMark } from '../../components/logo'
import { saveAllergy, saveDiet, saveHousehold } from '../../lib/api'
import { rollDecide } from '../../lib/decide'
import { toast } from '../../lib/nav'
import { useThemeClass } from '../../lib/theme'
import { markGuideAutoShown, markGuideCompleted } from '../../lib/user-settings'
import type { DecisionResult } from '@shared/types'

export default function OnboardingPage() {
  const themeClass = useThemeClass()
  // 从「我的 → 饭决偏好」进来是重设模式 (需求 8)。答完回设置页,
  // 而不是把用户甩到首页 —— 他是来改档案的, 不是来重新认识这个 App 的。
  const fromProfile =
    (Taro.getCurrentInstance().router?.params as { from?: string } | undefined)?.from === 'profile'
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState<OnboardingAnswers>({})
  const [pending, setPending] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<DecisionResult | null>(null)
  // 'intro' = 开场初始化动效; 'quiz' = 问答
  const [phase, setPhase] = useState<'intro' | 'quiz'>('intro')

  const question = ONBOARDING_QUESTIONS[index]

  // 开场动效 ~1.6s 后自动进入问卷; 轻触即开始
  // ⚠ 用全局 setTimeout / clearTimeout, 不要 Taro.setTimeout —— Taro 静态对象上没有
  //   这两个方法, runtime 里是 undefined, 调用即抛 "setTimeout is not a function"。
  useEffect(() => {
    if (phase !== 'intro') return
    const t = setTimeout(() => setPhase('quiz'), 1600)
    return () => clearTimeout(t)
  }, [phase])

  const startQuiz = () => setPhase('quiz')

  const finish = async (final: OnboardingAnswers) => {
    setSaving(true)
    const payload = toPreferencePayload(final)
    try {
      await Promise.all([
        saveDiet(payload.diet as unknown as Record<string, unknown>),
        saveAllergy(payload.allergy as unknown as Record<string, unknown>),
        saveHousehold(payload.household as unknown as Record<string, unknown>),
      ])
    } catch {
      // 档案没存上也要给结果 —— 用户后面可以在「我的 → 口味与忌口」自己改
      toast('偏好没保存成功，稍后可在设置里再改')
    }
    // 两个标记成对出现:
    //   completed  —— 长期: once 模式下以后都不再自动弹
    //   autoShown  —— 本次启动: 挡住"点进饭决回今日页又被守卫推回引导"的回弹,
    //                 即使 completed 因 storage 不可用没写成功也回得去
    markGuideCompleted()
    markGuideAutoShown()
    const { result: next } = await rollDecide(resolveMealSlot(), [])
    setSaving(false)
    setResult(next)
  }

  const commit = (value: string[]) => {
    const key = question.key as OnboardingKey
    const next: OnboardingAnswers = { ...answers, [key]: value }
    setAnswers(next)
    setPending([])
    if (index + 1 < ONBOARDING_TOTAL) {
      setIndex(index + 1)
      return
    }
    void finish(next)
  }

  const toggle = (value: string) => {
    setPending((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    )
  }

  // 开场初始化动效
  if (phase === 'intro') {
    return (
      <View className={`page ${themeClass}`}>
        <View className="onboard__intro" onClick={startQuiz}>
          <View className="obo-logo">
            <LogoMark size={76} />
          </View>
          {/* 7 颗点依次点亮, 呼应品牌「一周 7 天」的初始化配色动画 */}
          <View className="obo-dots" aria-hidden>
            {Array.from({ length: 7 }).map((_, i) => (
              <View key={i} className="obo-dots__item" style={{ animationDelay: `${i * 0.11}s` }} />
            ))}
          </View>
          <Text className="obo-intro-title">{brand.name}</Text>
          <Text className="obo-intro-sub">{brand.slogan}</Text>
          <Text className="obo-intro-hint">轻触开始</Text>
        </View>
      </View>
    )
  }

  // 第 4 屏: 结果。答完马上给答案, 不在这里做"设置成功"的过场。
  if (result) {
    return (
      <View className={`page ${themeClass}`}>
        <View className="onboard">
          <View className="onboard__result">
            <Text className="onboard__result-greet">{onboardingGreeting(result.meal_slot)}</Text>
            <Text className="onboard__result-dish">{result.dish.name}</Text>
            <Text className="onboard__result-reason">{result.reason}</Text>
            <Text className="onboard__result-meta">
              {formatMinutes(result.dish.cook_minutes)} · {result.dish.steps.length} 步
            </Text>
          </View>
          <PillButton
            block
            onClick={() => {
              if (fromProfile) {
                Taro.navigateBack()
                return
              }
              Taro.reLaunch({ url: '/pages/today/index' })
            }}
          >
            {fromProfile ? '回设置' : '进饭决'}
          </PillButton>
          <Text className="onboard__brand">{brand.slogan}</Text>
        </View>
      </View>
    )
  }

  if (!question) {
    return (
      <View className={`page ${themeClass}`}>
        <View className="onboard">
          <Text className="onboard__title">{onboardingGreeting(resolveMealSlot())}</Text>
          <Text className="onboard__hint">正在替你决定……</Text>
        </View>
      </View>
    )
  }

  return (
    <View className={`page ${themeClass}`}>
      <View className="onboard">
        <View className="onboard__progress">
          <LogoMark size={28} />
          <View className="onboard__progress-bar" aria-hidden>
            {ONBOARDING_QUESTIONS.map((q, i) => (
              <View
                key={q.key}
                className={`onboard__progress-seg ${i <= index ? 'onboard__progress-seg--on' : ''}`}
              />
            ))}
          </View>
          <Text className="onboard__step">
            {index + 1}/{ONBOARDING_TOTAL}
          </Text>
        </View>

        {/* key=index: 每切题重挂载, 触发进出场过渡动效 */}
        <View className="onboard__qwrap" key={index}>
          <Text className="onboard__title">{question.title}</Text>
          <Text className="onboard__hint">{question.subtitle}</Text>

          <View className="onboard__choices">
            {question.options.map((opt) => {
              const active = pending.includes(opt.value)
              return (
                <View
                  key={opt.value}
                  className={`onboard__choice onboard__choice--wide ${
                    active ? 'onboard__choice--active' : ''
                  }`}
                  onClick={() => (question.multiple ? toggle(opt.value) : commit([opt.value]))}
                >
                  <Text className="onboard__choice-label">{opt.label}</Text>
                  {opt.hint ? <Text className="onboard__choice-hint">{opt.hint}</Text> : null}
                  {active ? <Text className="onboard__choice-check" aria-hidden>✓</Text> : null}
                </View>
              )
            })}
          </View>

          {question.multiple ? (
            <View className="onboard__foot">
              <PillButton variant="ghost" onClick={() => commit([])}>
                {question.skipLabel ?? '跳过'}
              </PillButton>
              <PillButton
                block
                disabled={saving || pending.length === 0}
                onClick={() => commit(pending)}
              >
                {saving ? '决定中…' : '下一题'}
              </PillButton>
            </View>
          ) : (
            <View className="onboard__foot">
              <PillButton variant="ghost" onClick={() => commit([])}>
                跳过，用默认
              </PillButton>
            </View>
          )}
        </View>

        <Text className="onboard__brand">{brand.slogan}</Text>
      </View>
    </View>
  )
}
