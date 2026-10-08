/**
 * 饭决主决策区 (小程序) —— 需求 4 / 6 / 7 / 10
 *
 * 与 H5 的 components/DecideBoard.tsx 是同一张卡、同一条链路:
 *   没有结果 → 巨型主按钮「饭决」
 *   有结果   → 结果卡(菜名 + 一句话理由 + 步数/档位 + 3-5 步做法)
 *
 * 页面只有一个黑色实心按钮, 但它的文案随阶段推进:
 *   「就这个 → 开始做 → 做完了 → 饭决」—— 越往后选项越少, 不给回退的余地。
 * 其余一律文字链, 因为页面的主张是"别选了", 不能再给用户一堆等权重的按钮。
 *
 * ⚠ 卡上**不出现具体分钟数**。recipe.cook_minutes 是规则生成的品类基准值不是实测
 *   (全库 119 道菜都是 22 分钟 = 荤菜默认值, 连茶叶蛋也是 22 分钟)。把不可信的精确
 *   数字放到显眼位置 = 把数据缺陷放大成承诺破裂: 用户照着"15 分钟"安排今晚, 结果不是。
 *   时间维度只用于引擎内部过滤, 对外只给档位词: 快手 / 还行 / 要小火慢炖。
 *   步数从 dish.steps 真实算出, 这是可信的。
 *
 * 倔强阈值**按情境分档**(shared/decide-context.ts 的 stubbornAfter):
 *   深夜 2 次(耐心只有 8 秒) / 工作日 3 次 / 周末 5 次(人家在配一桌菜, 锁 3 次是负体验)。
 *   这里不写 `hour >= 22`, 也不写死 3 —— 那是"改一次漏一处"的经典现场。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Text, View } from '@tarojs/components'

import { brand } from '@shared/brand'
import { MEAL_SLOT_LABELS } from '@shared/decide'
import { contextBucket, stubbornAfter } from '@shared/decide-context'
import type { DecisionResult } from '@shared/types'

import { LogoMark } from './logo'
import UtteranceInput, { type UtteranceEcho } from './utterance-input'
import { buildResultCard } from '../lib/result-card'
import { track } from '../lib/track'
import { cookDecision } from '../lib/api'
import { toast } from '../lib/nav'
import {
  getRound,
  loadLastDecision,
  peekResult,
  rollDecide,
  sendDecideFeedback,
  syncProfile,
} from '../lib/decide'

const WEATHER_HINT: Record<string, string> = {
  rain: '外面在下雨',
  snow: '外面在下雪',
  hot: '今天挺热',
  cold: '今天挺冷',
}

/** 倔强提示的文案分档: 周末的人不是在纠结, 是在配一桌菜 (PRD R-12 ⑤) */
const STUBBORN_LINE: Record<string, string> = {
  weekend: '三菜一汤够了，开做吧',
  late_night: brand.stubbornLine,
  weekday: brand.stubbornLine,
}

/** 结果卡的阶段: 决定了 → 开始做 → 做完了 → (回到饭决, 下一顿) */
type Stage = 'result' | 'accepted' | 'cooking' | 'done'

/** 换一个 / 再来一个 / 全新一次 */
type RollIntent = 'fresh' | 'reroll' | 'another_dish'

/**
 * 决策本来就在 2 秒内返回, 快到不需要加载态。
 * 低于这个时长就把文案切走 —— 闪一下"正在替你决定"会制造"它很慢"的错觉,
 * 仪式感要放在结果揭晓上, 不是等待过程上。
 */
const SLOW_DECIDE_MS = 1200

/** `/decide/{id}/cook` 返回里一行被消耗/没扣到的食材 */
type CookConsumeLine = { ingredient_name: string; quantity: number; unit: string }

type CookDoneAck =
  /** 离线兜底出的结果 (id=0): 服务端没有这条决策记录, 没有东西可扣 */
  { kind: 'skipped' }
  /** 后端没有这道菜的 recipe_id (离线/本地菜): 只置了标记, 没扣减 */
  | { kind: 'no_recipe' }
  /** 幂等命中: 这顿之前已经做完并扣过 */
  | { kind: 'already' }
  | { kind: 'done'; consumed: CookConsumeLine[]; missing: CookConsumeLine[] }
  /** 请求失败: "做完了"这个事实成立, 但扣库存这一步没成功 */
  | { kind: 'failed' }

/**
 * 「做完了」的措辞 —— 后端每档返回都对应一句实话, 与 H5 的 DecideBoard 一致。
 *
 * 不允许统一说成"已扣减": 离线菜谱 / 重复点击 / 缺料 / 服务端失败这四种都是用户
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

export type DecideBoardProps = {
  /** 注入的时刻: 线上不传(取当前时间), 测试传固定值以覆盖深夜/周末 */
  now?: Date
}

export function DecideBoard({ now }: DecideBoardProps) {
  const [result, setLocal] = useState<DecisionResult | null>(() => peekResult())
  const [loading, setLoading] = useState(false)
  const [offline, setOffline] = useState(false)
  const [round, setRound] = useState(() => getRound())
  /** 真正换掉的那几道 —— 「已排除 N 道」只数它 */
  const [exclude, setExclude] = useState<string[]>([])
  /** 周末配菜定下的那几道 —— 不进"已排除", 她没在换菜 */
  const [picked, setPicked] = useState<string[]>([])
  const [stepsOpen, setStepsOpen] = useState(false)
  const [stubborn, setStubborn] = useState(false)
  const [locked, setLocked] = useState(false)
  const [stage, setStage] = useState<Stage>('result')
  const [slowDecide, setSlowDecide] = useState(false)
  const [utterance, setUtterance] = useState('')
  const [echo, setEcho] = useState<UtteranceEcho | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    // 冷启动先拿上次结果秒开, 顺带缓存决策档案给离线用
    void syncProfile()
    if (peekResult()) return
    void loadLastDecision().then((last) => {
      if (last) setLocal(last)
    })
  }, [])

  // 超过 1.2 秒还没回来才认作"慢"。快返回时根本不切文案, 也就没有"闪一下"
  useEffect(() => {
    if (!loading) {
      setSlowDecide(false)
      return
    }
    const timer = setTimeout(() => setSlowDecide(true), SLOW_DECIDE_MS)
    return () => clearTimeout(timer)
  }, [loading])

  const handleRoll = useCallback(
    async (intent: RollIntent) => {
      if (loading) return
      setLoading(true)
      setStepsOpen(false)
      setStage('result')
      setError('')

      const rerollIndex = exclude.length
      /**
       * ⚠ 先算出**本次请求要用的** exclude / picked, 再 setState。
       *   setState 是异步的, 直接拿闭包里的 exclude 拼请求体会漏掉刚换掉的这道 ——
       *   于是连点几次「换一个」会在两三道菜之间来回横跳, 正是这条名单要防的事。
       */
      let nextExclude = exclude
      let nextPicked = picked
      // 「换一个」= 不要这个: 推进 exclude
      if (intent === 'reroll' && result) {
        track('decide_reroll', { reroll_index: rerollIndex, reroll_intent: 'reroll' })
        track('decide_reject', {
          decision_id: result.id || null,
          dish: result.dish.name,
          reroll_index: rerollIndex,
        })
        // 前端从不调 feedback(false) 时 decision_log.accepted 大片 NULL, 「采纳率」等于没有
        void sendDecideFeedback(result.id, false)
        nextExclude = exclude.includes(result.dish.name)
          ? exclude
          : [...exclude, result.dish.name]
        setExclude(nextExclude)
      }
      if (intent === 'another_dish' && result) {
        track('decide_reroll', { reroll_index: rerollIndex, reroll_intent: 'another_dish' })
        // 只进 picked 不进 excluded: 她不是在换掉这道菜, 是在配一桌菜
        nextPicked = picked.includes(result.dish.name) ? picked : [...picked, result.dish.name]
        setPicked(nextPicked)
      }
      track('decide_roll', {
        reroll_index: rerollIndex,
        exclude_count: nextExclude.length,
        utterance_used: utterance.trim().length > 0,
        intent,
      })

      // 已定下的菜(picked)也一起排除: 周末配菜要的是"再来一道别的"
      const merged = Array.from(new Set([...nextExclude, ...nextPicked]))
      const { result: next, offline: isOffline } = await rollDecide(undefined, merged, utterance)
      setLoading(false)
      if (!next) {
        setError('暂时没法决定，稍后再试')
        return
      }
      setLocal(next)
      setOffline(isOffline)
      setRound(getRound())
      track('decide_result_shown', {
        decision_id: next.id || null,
        dish: next.dish.name,
        category: next.dish.category,
        main_ingredient: next.dish.main_ingredient,
        source: next.source,
        offline: isOffline,
        relaxed: Boolean(next.relaxed),
      })

      // 倔强阈值按情境分档, 不用写死的 3
      const at = now ?? new Date()
      const threshold = stubbornAfter(at)
      if (getRound() >= threshold && !locked) {
        setStubborn(true)
        setLocked(true)
        track('stubborn_shown', {
          bucket: contextBucket(at),
          threshold,
          round: getRound(),
        })
      }
    },
    [exclude, loading, locked, now, picked, result, utterance],
  )

  const card = useMemo(
    () =>
      buildResultCard({
        result,
        now,
        excludedCount: exclude.length,
        pickedCount: picked.length,
      }),
    [result, now, exclude.length, picked.length],
  )

  const weatherHint = result?.weather?.condition
    ? WEATHER_HINT[result.weather.condition]
    : undefined

  // 听懂了才改主按钮文案。没听懂时这里保持「饭决」—— 说了等于没说就别装作听见了
  const understood = Boolean(echo?.understood && utterance.trim())
  const actionLabel = understood ? '按你说的来' : brand.decideAction
  const busy = loading && slowDecide

  /**
   * 「做完了」: 真去扣库存 (POST /decide/{id}/cook), 再进 done 态
   *
   * ⚠ 顺序必须是先 await 结果、后切 done。反过来会先把"完成"演完再告诉你其实
   * 没扣成 —— 那是一次信任事故, 比不做这件事还糟。措辞由后端返回决定。
   */
  const handleCookDone = async () => {
    if (!result) return
    track('decide_cook_done', { decision_id: result.id || null, dish: result.dish.name })
    void sendDecideFeedback(result.id, true)

    // 离线兜底出的结果在服务端没有决策记录, 没东西可扣 —— 不假装有结果
    let ack: CookDoneAck = { kind: 'skipped' }
    if (result.id) {
      try {
        const res = await cookDecision(result.id)
        if (res.no_recipe) ack = { kind: 'no_recipe' }
        else if (res.already_cooked) ack = { kind: 'already' }
        else ack = { kind: 'done', consumed: res.consumed ?? [], missing: res.missing ?? [] }
      } catch {
        ack = { kind: 'failed' }
      }
    }
    setStage('done')
    const text = cookDoneText(ack)
    if (text) toast(text)
  }

  /** 黑色主按钮: 全页唯一一个, 文案随阶段推进 */
  const primary: { label: string; onClick: () => void } =
    stage === 'result'
      ? {
          label: '就这个',
          onClick: () => {
            if (!result) return
            track('decide_accept', {
              decision_id: result.id || null,
              dish: result.dish.name,
              reroll_index: exclude.length,
            })
            void sendDecideFeedback(result.id, true)
            setStepsOpen(true)
            setStage('accepted')
          },
        }
      : stage === 'accepted'
        ? {
            label: '开始做',
            onClick: () => {
              if (!result) return
              track('decide_cook_start', { decision_id: result.id || null, dish: result.dish.name })
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
          : { label: actionLabel, onClick: () => void handleRoll('fresh') }

  return (
    <View className="decide">
      {!result ? (
        <View className="decide__hero">
          <View className="decide__hero-logo">
            <LogoMark size={52} />
          </View>
          <Text className="decide__hero-title">{brand.name}</Text>
          <Text className="decide__hero-sub">{brand.slogan}</Text>
          <View
            className={`decide__button ${busy ? 'is-loading' : ''}`}
            onClick={() => void handleRoll('fresh')}
          >
            {/* 加载中文案刻意不提 AI: 那会把 2 秒承诺变成不确定等待 */}
            <Text className="decide__button-label">
              {busy ? '正在替你决定' : actionLabel}
            </Text>
          </View>
          {/* 无结果时在主按钮**下方**收起成一行引导: 空输入框摆在主按钮上方
              会让用户以为"得先填点什么" */}
          <UtteranceInput variant="hero" utterance={utterance} echo={echo} onChange={(text, next) => { setUtterance(text); setEcho(next) }} />
          {error ? <Text className="decide__error">{error}</Text> : null}
        </View>
      ) : (
        <View className={`decide__result ${offline ? 'is-offline' : ''}`}>
          <View className="decide__head">
            <Text className="decide__slot">{MEAL_SLOT_LABELS[result.meal_slot] ?? ''}</Text>
            {offline ? <Text className="decide__badge">{brand.offlineBadge}</Text> : null}
          </View>

          <Text className="decide__dish">{result.dish.name}</Text>
          <Text className="decide__reason">{result.reason}</Text>

          {/* 步数 + 档位词。⚠ 这一行永远不出现分钟数 */}
          <View className="decide__effort">
            <Text className="decide__effort-steps">{`${card.stepCount} 步`}</Text>
            <Text className="decide__effort-dot">·</Text>
            <Text className="decide__effort-label">{card.effortLabel}</Text>
            {/* 深夜不出现热量: 说教类信息在深夜是添堵 */}
            {card.showKcal && card.kcalText ? (
              <Text className="decide__effort-kcal">{card.kcalText}</Text>
            ) : null}
            {weatherHint ? <Text className="decide__effort-kcal">{weatherHint}</Text> : null}
          </View>

          {/* 简要步骤直接展示在按钮上方, 无需点「看做法」才能看到第一步 */}
          <View className="decide__steps-inline">
            {card.steps.map((step, index) => (
              <View className="decide__step-inline" key={step}>
                <Text className="decide__step-inline-idx">{index + 1}</Text>
                <Text className="decide__step-inline-text">{step}</Text>
              </View>
            ))}
          </View>

          {card.showAdvice && result.advice ? (
            <View className="decide__advice">
              <Text className="decide__advice-text">{result.advice}</Text>
            </View>
          ) : null}

          <View
            className={`decide__button decide__button--compact ${busy ? 'is-loading' : ''}`}
            onClick={primary.onClick}
          >
            <Text className="decide__button-label">
              {busy && stage === 'done' ? '正在替你决定' : primary.label}
            </Text>
          </View>

          <View className="decide__secondary">
            <Text
              className={`decide__link ${locked ? 'is-weak' : ''}`}
              onClick={() => void handleRoll('reroll')}
            >
              {busy ? '正在替你决定' : '换一个'}
            </Text>
            {/* 只在周末(含周五晚)10:00-20:00 出现: 她的「换一个」是"再来一个配菜" */}
            {card.showAnotherDish ? (
              <Text className="decide__link" onClick={() => void handleRoll('another_dish')}>
                再来一个
              </Text>
            ) : null}
            {stage === 'result' ? (
              <Text
                className="decide__link"
                onClick={() => {
                  if (!result) return
                  track('decide_view_steps', {
                    decision_id: result.id || null,
                    dish: result.dish.name,
                    steps: result.dish.steps.length,
                  })
                  setStepsOpen(true)
                }}
              >
                看做法
              </Text>
            ) : null}
            {stage === 'accepted' ? (
              <Text
                className="decide__link"
                onClick={() => {
                  void handleCookDone()
                }}
              >
                做完了
              </Text>
            ) : null}
          </View>

          {/* 有结果后才挪到动作行旁边: 真实诉求大多在看到候选之后才产生 */}
          <UtteranceInput variant="inline" utterance={utterance} echo={echo} onChange={(text, next) => { setUtterance(text); setEcho(next) }} />

          {/* 卡下方只留一条"系统侧事实/负面信息", 放宽优先 */}
          {card.footnote ? (
            <Text className="decide__note">{card.footnoteText}</Text>
          ) : null}
          {/* 周末配菜是正向事实(在配一桌菜), 不算负面信息, 可与上面并存 */}
          {card.pickedText ? (
            <Text className="decide__picked">
              {card.pickedText}：{picked.join(' + ')}
            </Text>
          ) : null}

          {locked ? <Text className="decide__locked">饭决已经替你定了，去做吧。</Text> : null}
        </View>
      )}

      {stepsOpen && result ? (
        <View className="decide__sheet" onClick={() => setStepsOpen(false)}>
          <View className="decide__sheet-card" onClick={(e) => e.stopPropagation()}>
            <View className="decide__sheet-head">
              <Text className="decide__sheet-title">{result.dish.name}</Text>
              {/* 同样只给步数与档位: 精确分钟数是规则基准值, 拿它当承诺会翻车 */}
              <Text className="decide__sheet-sub">
                {card.steps.length} 步 · {card.effortLabel}
              </Text>
            </View>
            <View className="decide__steps">
              {card.steps.map((step, index) => (
                <View className="decide__step" key={step}>
                  <Text className="decide__step-index">{index + 1}</Text>
                  <Text className="decide__step-text">{step}</Text>
                </View>
              ))}
            </View>
            {result.dish.ingredients.length ? (
              <View className="decide__ingredients">
                {result.dish.ingredients.map((item) => (
                  <Text className="decide__chip" key={item}>
                    {item}
                  </Text>
                ))}
              </View>
            ) : null}
            <Button className="decide__sheet-close" onClick={() => setStepsOpen(false)}>
              收起
            </Button>
          </View>
        </View>
      ) : null}

      {stubborn ? (
        <View className="decide__modal" onClick={() => setStubborn(false)}>
          <View className="decide__modal-card" onClick={(e) => e.stopPropagation()}>
            <Text className="decide__modal-text">
              {STUBBORN_LINE[contextBucket(now)] ?? brand.stubbornLine}
            </Text>
            <Button className="decide__modal-ok" onClick={() => setStubborn(false)}>
              听你的
            </Button>
          </View>
        </View>
      ) : null}
    </View>
  )
}

export default DecideBoard
