/**
 * 饭决主决策区 (需求 4 / 6 / 7 / 10) —— UI Demo 版式
 *
 * 布局照 《饭决 UI Demo.html》: 一张 .decision 大卡 = .decision-main + .decision-aside。
 *   * 空态: 「晚上，别纠结」+ 140px 黑色圆形「饭决」按钮 + ask 面板 (一句话诉求 + 情境 chips)
 *   * 结果态: 巨大菜名 / 橙色理由 / facts chips / 3-5 步直接展开 / 决策按钮行
 *   * aside: 空态给"这一顿怎么决定"的事实行; 结果态给 库存命中% + 食材 mini list
 *
 * 页面只有一个黑色实心按钮, 但它的文案随阶段推进: 出结果后走
 * 「就这个 → 开始做 → 做完了 → 饭决」这条渐进链路 —— 越往后选项越少, 不给回退的余地。
 *
 * ⚠ 卡上**不出现具体分钟数**。recipe.cook_minutes 是规则生成的品类基准值不是实测
 * (全库 119 道菜都是 22 分钟 = 荤菜默认值)。时间维度只用于引擎内部过滤,
 * 对外只给档位词: 快手 / 还行 / 要小火慢炖。步数是从 dish.steps 真实算出来的。
 *
 * 时刻靠 props 注入(默认 new Date()): tests/result-card.test.ts 用固定时刻跑三种情境。
 * 冰箱数据靠 props 注入(fridgeNames 等): aside 的库存命中%与"家里有"标记,
 * 组件本身不拉库存 —— 决策区不能因为库存接口挂了而出不了菜。
 *
 * 保住的三件品牌资产: 唯一黑色主按钮、做法直接展开不折叠、到点收手的倔强提示。
 */
import React, { useEffect, useMemo, useState } from 'react'
import { message } from 'antd'
import { brand } from '@shared/brand'
import { MEAL_SLOT_LABELS } from '@shared/decide'
import UtteranceInput from './UtteranceInput'
import { contextBucket } from '@shared/decide-context'
import { buildResultCard } from '../lib/result-card'
import {
  markCurrentExcluded,
  shouldShowStubborn,
  useDecideStore,
  type CookDoneAck,
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
  /** 冰箱里的食材名 —— aside 用来算库存命中% 与"家里有"标记 */
  fridgeNames?: string[]
  /** 冰箱食材总数 (aside 空态事实行) */
  fridgeCount?: number | null
  /** 临期食材数 (aside 空态事实行) */
  expiringCount?: number | null
}

/**
 * 「做完了」的措辞 —— 后端每档返回都对应一句实话。
 *
 * 不允许统一说成"已扣减": 离线菜谱、重复点击、缺料、服务端失败这四种都是用户
 * 立刻能在冰箱里对照出来的事实, 替后端说好话等于让用户发现系统在撒谎。
 */
function cookDoneText(ack: CookDoneAck): string {
  switch (ack.kind) {
    case 'skipped':
      return '已记下，但这次是离线结果，没有扣库存'
    case 'no_recipe':
      return '已记下，但这道是离线菜谱，没法精确扣库存'
    case 'already':
      return '这顿已经做完并扣过库存了'
    case 'done':
      return ack.missing.length > 0
        ? `已扣库存，${ack.missing.length} 样没扣到`
        : '已扣减冰箱库存'
    case 'failed':
      return '库存扣减失败，稍后可在冰箱里手动调整'
    default:
      return ''
  }
}

/** Demo 空态的时段问候: 「今晚，别纠结」 */
function leadOf(date: Date): string {
  const h = date.getHours()
  if (h < 5) return '夜里'
  if (h < 10) return '早上'
  if (h < 14) return '中午'
  if (h < 17) return '下午'
  if (h < 22) return '今晚'
  return '夜里'
}

/** 食材命中判定: 名称互相包含即算(菜谱写「西红柿」冰箱记「番茄」这类由别名表在引擎侧解) */
function isOwned(ingredient: string, fridgeNames: string[]): boolean {
  return fridgeNames.some((name) => ingredient.includes(name) || name.includes(ingredient))
}

const DecideBoard: React.FC<DecideBoardProps> = ({
  now,
  fridgeNames,
  fridgeCount,
  expiringCount,
}) => {
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
    reset,
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

  /**
   * 「做完了」: 真去扣库存 (POST /decide/{id}/cook), 再进 done 态
   *
   * ⚠ 顺序必须是先 await 结果、后切 done。反过来会先把"完成"演完再告诉你其实
   * 没扣成 —— 那是一次信任事故, 比不做这件事还糟。措辞由后端返回决定。
   */
  const handleCookDone = async () => {
    const ack = await cookDone()
    setStage('done')
    const text = cookDoneText(ack)
    if (text) message.info(text)
  }

  /** 「重新开始」: 回到空态 —— store 的 reset 同时清掉 utterance/excluded/picked */
  const handleClear = () => {
    setStepsOpen(false)
    setStage('result')
    setLocked(false)
    reset()
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
                void handleCookDone()
              },
            }
          : { label: actionLabel, onClick: () => void handleReroll() }

  // aside 的库存命中: 只在结果态、且页面给了冰箱名单时计算
  const stockHits = useMemo(() => {
    if (!result || !fridgeNames) return null
    const total = result.dish.ingredients.length
    if (total === 0) return null
    const hits = result.dish.ingredients.filter((ing) => isOwned(ing, fridgeNames)).length
    return { hits, total, percent: Math.round((hits / total) * 100) }
  }, [result, fridgeNames])

  const clock = now ?? new Date()

  return (
    <>
      <section className="decision card">
        {!result ? (
          <div className="decision-main decision-empty">
            <h2>{leadOf(clock)}，别纠结</h2>
            <p className="slogan">按一下，我替你定</p>
            <button
              type="button"
              className="decide-orb"
              onClick={() => void roll({ intent: 'fresh' })}
              disabled={loading}
            >
              {/* 加载中文案刻意不提 AI: 那会把 2 秒承诺变成不确定等待 */}
              {busy ? '决定中' : '饭决'}
            </button>
            <UtteranceInput variant="hero" />
            {error ? <div className="decide-error">{error}</div> : null}
          </div>
        ) : (
          // key 换掉 = 整卡重挂, 结果揭晓的缓出才会每道菜都演一遍
          <div key={`${result.dish.name}-${result.decided_at}`} className="decision-main">
            <div className="dish-kicker">
              <span>{MEAL_SLOT_LABELS[result.meal_slot] ?? ''}</span>
              <span>·</span>
              <span>{understood ? `已按「${utterance}」` : '库存优先'}</span>
              {offline ? <span className="tag warn">{brand.offlineBadge}</span> : null}
            </div>

            <h2 className="dish-name">{result.dish.name}</h2>
            <div className="dish-reason">{result.reason}</div>

            {/* 步数从 steps 真实算出; 档位词取代了不可信的精确分钟数 */}
            <div className="dish-facts">
              <span>{card.stepCount} 步</span>
              <span>{card.effortLabel}</span>
              {/* 深夜不出现热量: 说教类信息在深夜是添堵, 不是提醒 */}
              {card.showKcal && card.kcalText ? <span>{card.kcalText}</span> : null}
              {weatherHint ? <span>{weatherHint}</span> : null}
            </div>

            {/* 简要步骤直接展示, 无需点击「看做法」再展开 */}
            <ol className="steps">
              {card.steps.map((step, index) => (
                <li key={step}>
                  <i>{index + 1}</i>
                  <span>{step}</span>
                </li>
              ))}
            </ol>

            {card.showAdvice && result.advice ? (
              <div className="aside-note" style={{ marginTop: 14 }}>
                {result.advice}
              </div>
            ) : null}

            {stage === 'done' ? (
              <div className="success-line">这顿做完了，库存扣减情况见上方提示。</div>
            ) : null}

            <div className="decision-actions">
              <button
                type="button"
                className="button primary"
                onClick={primary.onClick}
                disabled={busy && stage === 'done'}
              >
                {busy && stage === 'done' ? '正在替你决定' : primary.label}
              </button>

              <button
                type="button"
                className="text-button"
                onClick={() => void handleReroll()}
                disabled={loading}
              >
                {busy ? '正在替你决定' : locked ? '再想想' : '换一个'}
              </button>
              {/* 只在周末出现: 她的「换一个」是"再来一个配菜", 不是"不要这个" */}
              {card.showAnotherDish ? (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => void handleAnotherDish()}
                  disabled={loading}
                >
                  再来一个
                </button>
              ) : null}
              {stage === 'result' ? (
                <button
                  type="button"
                  className="text-button"
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
                  className="text-button"
                  onClick={() => {
                    void handleCookDone()
                  }}
                >
                  做完了
                </button>
              ) : null}
              <button type="button" className="text-button" onClick={handleClear}>
                重新开始
              </button>
            </div>

            {/* 有结果后才挪到这里: 真实诉求大多在看到候选之后才产生 */}
            <UtteranceInput variant="inline" />

            {/*
              卡下方只留一条"系统侧事实/负面信息", 放宽优先:
              条件放宽时理由已经退化成"可选项不多了, 就它吧", 这时候再叠加
              "已排除 8 道", 用户读出来的是"饭决品味变差了 + 系统在死磕"。
            */}
            {card.footnote ? <div className="decide-note">{card.footnoteText}</div> : null}
            {/* 周末配菜是正向事实(在配一桌菜), 不算负面信息, 可与上面并存 */}
            {card.pickedText ? (
              <div className="decide-note">
                {card.pickedText}：{picked.join(' + ')}
              </div>
            ) : null}

            {locked ? <div className="decide-locked">饭决已经替你定了，去做吧。</div> : null}
          </div>
        )}

        <aside className="decision-aside">
          {!result ? (
            <>
              <div>
                <h3>这一顿怎么决定</h3>
                <div className="aside-list">
                  <div className="aside-row">
                    <span>临期食材</span>
                    <b>{expiringCount != null ? `${expiringCount} 样` : '—'}</b>
                  </div>
                  <div className="aside-row">
                    <span>家里有</span>
                    <b>{fridgeCount != null ? `${fridgeCount} 样` : '—'}</b>
                  </div>
                  <div className="aside-row">
                    <span>最近吃过</span>
                    <b>自动避开</b>
                  </div>
                </div>
              </div>
              <p className="aside-note">
                不需要先填完整资料。没有命中库存时，也会给出一份能落地的家常菜。
              </p>
            </>
          ) : (
            <>
              <div>
                {stockHits ? (
                  <span className={`tag ${stockHits.percent >= 50 ? 'good' : ''}`}>
                    库存命中 {stockHits.percent}%
                  </span>
                ) : (
                  <span className="tag">本地答案</span>
                )}
                <div className="aside-dish" style={{ marginTop: 14 }}>
                  {result.dish.name}
                </div>
                <div className="ingredient-mini">
                  {result.dish.ingredients.map((ing) => (
                    <div key={ing}>
                      <span>{ing}</span>
                      <strong>
                        {fridgeNames ? (isOwned(ing, fridgeNames) ? '家里有' : '要补') : ''}
                      </strong>
                    </div>
                  ))}
                </div>
              </div>
              <p className="aside-note">主按钮会依次推进“定下 → 开始做 → 做完了”，减少来回选择。</p>
            </>
          )}
        </aside>
      </section>

      {stepsOpen && result ? (
        <StepsSheet result={result} steps={card.steps} effortLabel={card.effortLabel} onClose={() => setStepsOpen(false)} />
      ) : null}

      {stubborn ? (
        <div className="modal-overlay open" role="dialog" onClick={() => setStubborn(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <p style={{ fontSize: 16, lineHeight: 1.6 }}>
              {STUBBORN_LINE[contextBucket(now)] ?? brand.stubbornLine}
            </p>
            <div className="modal-actions">
              <button type="button" className="button primary" onClick={() => setStubborn(false)}>
                听你的
              </button>
            </div>
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
  <div className="modal-overlay open" role="dialog" onClick={onClose}>
    <div className="modal" onClick={(e) => e.stopPropagation()}>
      <h2>{result.dish.name}</h2>
      {/* 同样只给步数与档位: 精确分钟数是规则基准值, 拿它当承诺会翻车 */}
      <div className="card-sub">
        {steps.length} 步 · {effortLabel}
      </div>
      <ol className="steps">
        {steps.map((step, index) => (
          <li key={step}>
            <i>{index + 1}</i>
            <span>{step}</span>
          </li>
        ))}
      </ol>
      {result.dish.ingredients.length ? (
        <div className="dish-facts">
          {result.dish.ingredients.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : null}
      <div className="modal-actions">
        <button type="button" className="button primary" onClick={onClose}>
          收起
        </button>
      </div>
    </div>
  </div>
)

export default DecideBoard
