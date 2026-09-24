/**
 * 饭决主决策区 (需求 4 / 6 / 7 / 10)
 *
 * 页面只有一个黑色实心按钮, 但它的文案随阶段推进: 无结果是「饭决」,
 * 出结果后走「就这个 → 开始做 → 做完了 → 饭决」这条渐进链路 ——
 * 越往后选项越少, 不给回退的余地。其余一律浅灰胶囊或文字链,
 * 因为页面的主张是"别选了", 不能再给用户一堆等权重的按钮。
 *
 * 结果卡的展示顺序: 菜名 → 一句话理由 → 步数 + 档位 → 3-5 步做法。
 *
 * ⚠ 卡上**不出现具体分钟数**。recipe.cook_minutes 是规则生成的品类基准值不是实测
 * (全库 119 道菜都是 22 分钟 = 荤菜默认值, 连茶叶蛋也是 22 分钟)。把不可信的精确数字
 * 放到显眼位置, 等于把数据缺陷放大成承诺破裂: 用户照着"15 分钟"安排今晚, 结果不是。
 * 时间维度只用于引擎内部过滤(出餐上限 / 深夜阈值), 对外只给档位词: 快手 / 还行 / 要小火慢炖。
 * 步数是从 dish.steps 真实算出来的, 这是可信的, 正好也呼应"3-5 步极简做法直接展开"。
 *
 * 时刻靠 props 注入(默认 new Date()):
 *   深夜 / 周末这些判断没人会真的等到 23:40 去点一遍验证, 而 vi.useFakeTimers()
 *   会连 zustand 的定时器一起假掉, 污染整个测试环境。所以组件收一个 now,
 *   tests/result-card.test.ts 用固定时刻把三种情境一次跑完。
 *
 * 保住的三件品牌资产: 唯一黑色主按钮、做法直接展开不折叠、到点收手的倔强提示。
 */
import React, { useEffect, useMemo, useState } from 'react'
import { brand } from '@shared/brand'
import { MEAL_SLOT_LABELS } from '@shared/decide'
import { LogoMark } from './ui/logo'
import UtteranceInput from './UtteranceInput'
import { contextBucket } from '@shared/decide-context'
import { buildResultCard } from '../lib/result-card'
import {
  markCurrentExcluded,
  shouldShowStubborn,
  useDecideStore,
} from '../stores/useDecideStore'
import type { DecisionResult } from '../types'

/** 倔强提示的文案分档: 周末的人不是在纠结, 是在配一桌菜 (PRD R-12 ⑤) */
const STUBBORN_LINE: Record<string, string> = {
  weekend: '三菜一汤够了，开做吧',
  late_night: brand.stubbornLine,
  weekday: brand.stubbornLine,
}

/** 结果卡的阶段: 决定了 → 开始做 → 做完了 → (回到饭决, 下一顿) */
type Stage = 'result' | 'accepted' | 'cooking' | 'done'

/**
 * 决策本来就在 2 秒内返回, 快到不需要加载态。
 * 低于这个时长就把 spinner/文案切走 —— 闪一下"正在替你决定"会制造"它很慢"的错觉,
 * 仪式感要放在结果揭晓上, 不是等待过程上。
 */
const SLOW_DECIDE_MS = 1200

export type DecideBoardProps = {
  /** 注入的时刻: 线上不传(取当前时间), 测试传固定值以覆盖深夜/周末 */
  now?: Date
}

const DecideBoard: React.FC<DecideBoardProps> = ({ now }) => {
  const {
    result,
    loading,
    offline,
    round,
    stubbornShown,
    error,
    excluded,
    picked,
    utterance,
    intent,
    ensure,
    roll,
    accept,
    viewSteps,
    cookStart,
    cookDone,
    noteStubbornShown,
  } = useDecideStore()
  const [stepsOpen, setStepsOpen] = useState(false)
  const [stubborn, setStubborn] = useState(false)
  const [locked, setLocked] = useState(false)
  const [stage, setStage] = useState<Stage>('result')
  const [slowDecide, setSlowDecide] = useState(false)

  useEffect(() => {
    void ensure()
  }, [ensure])

  useEffect(() => {
    if (shouldShowStubborn(round, stubbornShown, now)) {
      setStubborn(true)
      setLocked(true) // 倔一回: 锁住当前结果, 「换一个」降级
      noteStubbornShown(now)
    }
  }, [round, stubbornShown, noteStubbornShown, now])

  // 超过 1.2 秒还没回来才认作"慢"。快返回时根本不切文案, 也就没有"闪一下"
  useEffect(() => {
    if (!loading) {
      setSlowDecide(false)
      return
    }
    const timer = setTimeout(() => setSlowDecide(true), SLOW_DECIDE_MS)
    return () => clearTimeout(timer)
  }, [loading])

  // 听懂了才改主按钮文案。没听懂时这里保持「饭决」—— 说了等于没说就别装作听见了
  const understood = Boolean(intent?.understood && utterance.trim())
  const actionLabel = understood ? '按你说的来' : brand.decideAction
  const busy = loading && slowDecide

  /** 换掉当前: 推入 exclude(否则连点几次会在两三道菜之间来回横跳) + 上报 reject */
  const handleReroll = async () => {
    setStepsOpen(false)
    setStage('result')
    markCurrentExcluded('reroll')
    await roll({ intent: 'reroll' })
  }

  /** 周末配菜: 当前这道留下(进 picked), 再要一道 */
  const handleAnotherDish = async () => {
    setStepsOpen(false)
    setStage('result')
    markCurrentExcluded('another_dish')
    await roll({ intent: 'another_dish' })
  }

  const card = useMemo(
    () => buildResultCard({ result, now, excludedCount: excluded.length, pickedCount: picked.length }),
    [result, now, excluded.length, picked.length],
  )

  const weatherHint = result?.weather?.condition
    ? { rain: '外面在下雨', snow: '外面在下雪', hot: '今天挺热', cold: '今天挺冷' }[
        result.weather.condition
      ]
    : undefined

  /** 黑色主按钮: 全页唯一一个, 文案随阶段推进 */
  const primary: { label: string; onClick: () => void } =
    stage === 'result'
      ? {
          label: '就这个',
          onClick: () => {
            accept()
            setStepsOpen(true)
            setStage('accepted')
          },
        }
      : stage === 'accepted'
        ? {
            label: '开始做',
            onClick: () => {
              cookStart()
              setStepsOpen(true)
              setStage('cooking')
            },
          }
        : stage === 'cooking'
          ? {
              label: '做完了',
              onClick: () => {
                cookDone()
                setStage('done')
              },
            }
          : { label: actionLabel, onClick: () => void handleReroll() }

  return (
    <>
      <section className="decide-board">
        {!result ? (
          <div className="decide-hero">
            <div className="decide-hero-logo">
              <LogoMark size={56} />
            </div>
            <div className="decide-hero-title">{brand.name}</div>
            <div className="decide-hero-sub">{brand.slogan}</div>
            <button
              type="button"
              className={`decide-button ${busy ? 'is-loading' : ''}`}
              onClick={() => void roll({ intent: 'fresh' })}
              disabled={loading}
            >
              {/* 加载中文案刻意不提 AI: 那会把 2 秒承诺变成不确定等待 */}
              <span className="decide-button-label">
                {busy ? '正在替你决定' : actionLabel}
              </span>
            </button>
            <UtteranceInput variant="hero" />
            {error ? <div className="decide-error">{error}</div> : null}
          </div>
        ) : (
          // key 换掉 = 整卡重挂, 结果揭晓的 180ms 缓出才会每道菜都演一遍
          <div
            key={`${result.dish.name}-${result.decided_at}`}
            className={`decide-result ${offline ? 'is-offline' : ''}`}
          >
            <div className="decide-result-head">
              <span className="decide-slot">{MEAL_SLOT_LABELS[result.meal_slot] ?? ''}</span>
              {offline ? <span className="decide-badge">{brand.offlineBadge}</span> : null}
            </div>

            <div className="decide-dish-name">{result.dish.name}</div>
            <div className="decide-reason">{result.reason}</div>

            {/* 步数从 steps 真实算出; 档位词取代了不可信的精确分钟数 */}
            <div className="decide-effort">
              <span className="decide-effort__steps">{`${card.stepCount} 步`}</span>
              <span className="decide-effort__dot">·</span>
              <span className="decide-effort__label">{card.effortLabel}</span>
              {/* 深夜不出现热量: 说教类信息在深夜是添堵, 不是提醒 */}
              {card.showKcal && card.kcalText ? (
                <span className="decide-effort__kcal">{card.kcalText}</span>
              ) : null}
              {weatherHint ? <span className="decide-effort__kcal">{weatherHint}</span> : null}
            </div>

            {/* 简要步骤直接展示, 无需点击「看做法」再展开 */}
            <ol className="decide-steps-inline">
              {card.steps.map((step, index) => (
                <li key={step}>
                  <span className="decide-steps-inline__idx">{index + 1}</span>
                  <span className="decide-steps-inline__text">{step}</span>
                </li>
              ))}
            </ol>

            {card.showAdvice && result.advice ? (
              <div className="decide-advice">{result.advice}</div>
            ) : null}

            <div className="decide-actions">
              <button
                type="button"
                className={`decide-button decide-button--compact ${busy ? 'is-loading' : ''}`}
                onClick={primary.onClick}
                disabled={busy && stage === 'done'}
              >
                <span className="decide-button-label">
                  {busy && stage === 'done' ? '正在替你决定' : primary.label}
                </span>
              </button>

              <div className="decide-secondary">
                <button
                  type="button"
                  className={`decide-link ${locked ? 'is-weak' : ''}`}
                  onClick={() => void handleReroll()}
                  disabled={loading}
                >
                  {busy ? '正在替你决定' : '换一个'}
                </button>
                {/* 只在周末出现: 她的「换一个」是"再来一个配菜", 不是"不要这个" */}
                {card.showAnotherDish ? (
                  <button
                    type="button"
                    className="decide-link"
                    onClick={() => void handleAnotherDish()}
                    disabled={loading}
                  >
                    再来一个
                  </button>
                ) : null}
                {stage === 'result' ? (
                  <button
                    type="button"
                    className="decide-link"
                    onClick={() => {
                      viewSteps()
                      setStepsOpen(true)
                    }}
                  >
                    看做法
                  </button>
                ) : null}
                {stage === 'accepted' ? (
                  <button
                    type="button"
                    className="decide-link"
                    onClick={() => {
                      cookDone()
                      setStage('done')
                    }}
                  >
                    做完了
                  </button>
                ) : null}
              </div>

              {/* 有结果后才挪到这里: 真实诉求大多在看到候选之后才产生 */}
              <UtteranceInput variant="inline" />
            </div>

            {/*
              卡下方只留一条"系统侧事实/负面信息", 放宽优先:
              条件放宽时理由已经退化成"可选项不多了, 就它吧", 这时候再叠加
              "已排除 8 道", 用户读出来的是"饭决品味变差了 + 系统在死磕"。
              不标注才会被当成品味问题 —— 那是比数据缺陷更贵的信任损失。
            */}
            {card.footnote ? (
              <div className={`decide-note decide-note--${card.footnote}`}>
                {card.footnoteText}
              </div>
            ) : null}
            {/* 周末配菜是正向事实(在配一桌菜), 不算负面信息, 可与上面并存 */}
            {card.pickedText ? (
              <div className="decide-excluded">{card.pickedText}：{picked.join(' + ')}</div>
            ) : null}

            {locked ? <div className="decide-locked">饭决已经替你定了，去做吧。</div> : null}
          </div>
        )}
      </section>

      {stepsOpen && result ? (
        <StepsSheet result={result} steps={card.steps} effortLabel={card.effortLabel} onClose={() => setStepsOpen(false)} />
      ) : null}

      {stubborn ? (
        <div className="decide-modal" role="dialog" onClick={() => setStubborn(false)}>
          <div className="decide-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="decide-modal-text">
              {STUBBORN_LINE[contextBucket(now)] ?? brand.stubbornLine}
            </div>
            <button type="button" className="decide-modal-ok" onClick={() => setStubborn(false)}>
              听你的
            </button>
          </div>
        </div>
      ) : null}
    </>
  )
}

/** 极简做法卡: 3-5 步一屏看完 (需求 10) */
const StepsSheet: React.FC<{
  result: DecisionResult
  steps: string[]
  effortLabel: string
  onClose: () => void
}> = ({ result, steps, effortLabel, onClose }) => (
  <div className="decide-sheet" role="dialog" onClick={onClose}>
    <div className="decide-sheet-card" onClick={(e) => e.stopPropagation()}>
      <div className="decide-sheet-head">
        <div className="decide-sheet-title">{result.dish.name}</div>
        {/* 同样只给步数与档位: 精确分钟数是规则基准值, 拿它当承诺会翻车 */}
        <div className="decide-sheet-sub">
          {steps.length} 步 · {effortLabel}
        </div>
      </div>
      <ol className="decide-steps">
        {steps.map((step, index) => (
          <li key={step}>
            <span className="decide-step-index">{index + 1}</span>
            <span className="decide-step-text">{step}</span>
          </li>
        ))}
      </ol>
      {result.dish.ingredients.length ? (
        <div className="decide-sheet-ingredients">
          {result.dish.ingredients.map((item) => (
            <span key={item} className="decide-chip">
              {item}
            </span>
          ))}
        </div>
      ) : null}
      <button type="button" className="decide-sheet-close" onClick={onClose}>
        收起
      </button>
    </div>
  </div>
)

export default DecideBoard
