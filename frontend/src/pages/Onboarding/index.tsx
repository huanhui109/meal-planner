/**
 * 饭决 Onboarding (需求 1: ≤60 秒)
 *
 * 三问三屏, 每屏 1 次点选, 每屏都能跳过。
 *
 * 与旧版引导最大的区别: **答完立刻出结果**。
 * 旧版走完引导还要等 1-2 分钟生成周菜单才看到东西 —— 那是"被决定的爽感"的断点。
 * 这里答完第 3 题直接在引导页里给出第一张结果卡, 用户还没进首页就已经吃过一次甜头。
 *
 * V1.1 体验升级 (参考苹果新装 iOS 指引):
 *   - 开场「初始化」动效: Logo 缩放淡入 + 7 颗点依次点亮 (呼应品牌「一周 7 天」),
 *     轻触即进入问卷, 也可 ~1.6s 后自动进入, 不增加决策摩擦。
 *   - 分段进度条取代纯文字「1/3」, 进度一目了然。
 *   - 每题进出场过渡 + 选项选中态强化 (描边/底色/对勾), 引导更顺。
 */
import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { message } from 'antd'
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
import { LogoMark } from '../../components/ui/logo'
import { updateAllergy, updateDiet, updateHousehold } from '../../api/preferences'
import { markGuideAutoShown, markGuideCompleted } from '../../lib/user-settings'
import { useDecideStore } from '../../stores/useDecideStore'

const Onboarding: React.FC = () => {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // 从「我的 → 饭决偏好」进来是重设模式 (需求 8: 一次设置长期生效, 但随时能改),
  // 答完回设置页而不是首页 —— 用户是来改档案的, 不是来重新认识这个 App 的。
  const backTo = params.get('from') === 'preferences' ? '/preferences' : '/'
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState<OnboardingAnswers>({})
  const [pending, setPending] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  // 'intro' = 开场初始化动效; 'quiz' = 问答
  const [phase, setPhase] = useState<'intro' | 'quiz'>('intro')
  const roll = useDecideStore((s) => s.roll)

  const question = ONBOARDING_QUESTIONS[index]

  // 开场动效 ~1.6s 后自动进入问卷; 期间轻触任意处可立即开始
  useEffect(() => {
    if (phase !== 'intro') return
    const t = window.setTimeout(() => setPhase('quiz'), 1600)
    return () => window.clearTimeout(t)
  }, [phase])

  const startQuiz = () => setPhase('quiz')

  const finish = async (finalAnswers: OnboardingAnswers) => {
    setSaving(true)
    const payload = toPreferencePayload(finalAnswers)
    try {
      await Promise.all([
        updateDiet(payload.diet),
        updateAllergy(payload.allergy),
        updateHousehold(payload.household),
      ])
    } catch (error) {
      // 档案没存上也要给结果 —— 引导的目的是尽快吃到第一个答案, 不是为了存档
      message.warning((error as Error).message || '偏好没保存成功，稍后可在设置里再改')
    }
    // 两个标记必须成对出现:
    //   completed  —— 长期: once 模式下以后都不再自动弹
    //   autoShown  —— 本次启动: 挡住"回首页又被守卫推回引导"的回弹,
    //                 即使上面 completed 因 localStorage 不可用没写成功也回得去
    markGuideCompleted()
    markGuideAutoShown()
    await roll({ intent: 'fresh' })
    setSaving(false)
    navigate(backTo, { replace: true })
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
    setPending((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]))
  }

  const greeting = useMemo(() => onboardingGreeting(resolveMealSlot()), [])

  // 答完第 3 题、roll 尚未返回前的「正在决定」过场 (兜底, 正常路径 finish 会直接 navigate)
  if (!question) {
    return (
      <div className="onboarding">
        <div className="onboarding-card onboarding-card--center">
          <div className="obo-logo obo-logo--spin">
            <LogoMark size={48} />
          </div>
          <div className="onboarding-done-title">{greeting}</div>
          <div className="onboarding-done-sub">正在替你决定……</div>
        </div>
      </div>
    )
  }

  // 开场初始化动效
  if (phase === 'intro') {
    return (
      <div className="onboarding">
        <div
          className="onboarding-intro"
          role="button"
          tabIndex={0}
          onClick={startQuiz}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              startQuiz()
            }
          }}
        >
          <div className="obo-logo">
            <LogoMark size={76} />
          </div>
          {/* 7 颗点依次点亮, 呼应品牌「一周 7 天」的初始化配色动画 */}
          <div className="obo-dots" aria-hidden>
            {Array.from({ length: 7 }).map((_, i) => (
              <span key={i} style={{ animationDelay: `${i * 0.11}s` }} />
            ))}
          </div>
          <div className="obo-intro-title">{brand.name}</div>
          <div className="obo-intro-sub">{brand.slogan}</div>
          <div className="obo-intro-hint">轻触开始</div>
        </div>
      </div>
    )
  }

  return (
    <div className="onboarding">
      <div className="onboarding-card">
        <div className="onboarding-top">
          <LogoMark size={30} />
          <div className="onboarding-progress-bar" aria-hidden>
            {ONBOARDING_QUESTIONS.map((q, i) => (
              <span
                key={q.key}
                className={`onboarding-progress-seg ${i <= index ? 'is-done' : ''}`}
              />
            ))}
          </div>
          <div className="onboarding-step-count">
            {index + 1}/{ONBOARDING_TOTAL}
          </div>
        </div>

        {/* key=index: 每切题重挂载, 触发进出场过渡动效 */}
        <div className="onboarding-qwrap" key={index}>
          <div className="onboarding-q">{question.title}</div>
          <div className="onboarding-sub">{question.subtitle}</div>

          <div className="onboarding-options">
            {question.options.map((option) => {
              const active = question.multiple ? pending.includes(option.value) : false
              return (
                <button
                  key={option.value}
                  type="button"
                  className={`onboarding-option ${active ? 'is-active' : ''}`}
                  onClick={() => (question.multiple ? toggle(option.value) : commit([option.value]))}
                >
                  <span className="onboarding-option-label">{option.label}</span>
                  {option.hint ? <span className="onboarding-option-hint">{option.hint}</span> : null}
                  {active ? (
                    <span className="onboarding-option-check" aria-hidden>
                      ✓
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>
        </div>

        <div className="onboarding-foot">
          {question.multiple ? (
            <>
              <button
                type="button"
                className="onboarding-skip"
                onClick={() => commit([])}
                disabled={saving}
              >
                {question.skipLabel ?? '跳过'}
              </button>
              <button
                type="button"
                className="onboarding-next"
                onClick={() => commit(pending)}
                disabled={saving || pending.length === 0}
              >
                {saving ? '正在决定…' : '下一题'}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="onboarding-skip"
              onClick={() => commit([])}
              disabled={saving}
            >
              跳过，用默认
            </button>
          )}
        </div>

        <div className="onboarding-brand">{brand.slogan}</div>
      </div>
    </div>
  )
}

export default Onboarding
