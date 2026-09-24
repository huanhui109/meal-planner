/**
 * 一句话诉求输入 (utterance)
 *
 * 三条不可协商的规则:
 *   1. **永远可空。** 产品承诺是"不说直接按", 不是"先说话再按"。空着点主按钮,
 *      请求体 utterance 是空串, 行为与没这个输入框时完全一致。
 *   2. **没听懂就不回显。** understood=false 时这里不渲染任何东西 ——
 *      不是 display:none, 是根本不生成节点。猜错之后再改用户的菜, 比不说更伤。
 *   3. **解析失败完全静默。** 连 toast 都不弹: 它只是"我被听见了"的确认,
 *      为它打断决策不值得。
 *
 * 位置随状态变化(不是固定放在主按钮上方):
 *   - 无结果时在主按钮下方, 默认收起成一行引导 —— 一个空输入框摆在主按钮上方,
 *     用户的第一反应是"我是不是得填点什么", 那正好是反模式 1。
 *   - 有结果时挪到「换一个」那一行旁边 —— 真实诉求大多在**看到候选之后**才产生
 *     ("看到宫保鸡丁才想起昨天吃过")。
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { understandUtterance } from '../api/decide'
import { contextBucket } from '@shared/decide-context'
import { useDecideStore } from '../stores/useDecideStore'

const PLACEHOLDER = '比如：清淡点，别太辣'

/** 引导语按时段换语气: 同一件事在不同时刻说法不同 (瑞思 §4.2) */
const GUIDE_BY_BUCKET: Record<string, string> = {
  late_night: '夜宵想吃点啥？不说我定',
  weekend: '想做几个菜？说一声也行',
  weekday: '想说点什么也行，不说直接按',
}

/** 情境 chip, 最多 3 个 —— 超过 3 个就从"快捷说法"变成筛选器了 */
const CHIPS_BY_BUCKET: Record<string, string[]> = {
  late_night: ['清淡点', '十分钟搞定', '冰箱有啥用啥'],
  weekend: ['孩子也吃', '来个汤', '换个配菜'],
  weekday: ['二十分钟搞定', '别太麻烦', '冰箱里有啥用啥'],
}

/** 把结构化意图翻译成给用户看的一行约束, 最多 3 个词 */
function echoOf(intent: {
  require_light?: boolean
  max_spice?: number | null
  max_minutes?: number | null
  prefer_fridge?: boolean
  avoid_meat?: boolean
  category?: string | null
  avoid?: string[]
}): string[] {
  const out: string[] = []
  if (intent.require_light) out.push('清淡')
  if (intent.max_spice === 0) out.push('不辣')
  if (intent.max_minutes != null) out.push(`${intent.max_minutes} 分钟内`)
  if (intent.prefer_fridge) out.push('用冰箱现有的')
  if (intent.avoid_meat) out.push('不吃肉')
  if (intent.category) out.push(`要个${intent.category}`)
  if (intent.avoid?.length) out.push(`不要${intent.avoid.slice(0, 2).join('、')}`)
  return out.slice(0, 3)
}

const UtteranceInput: React.FC<{ variant?: 'hero' | 'inline' }> = ({ variant = 'hero' }) => {
  const { utterance, intent, setUtterance } = useDecideStore()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(utterance)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const bucket = contextBucket()
  const guide = GUIDE_BY_BUCKET[bucket] ?? GUIDE_BY_BUCKET.weekday
  const chips = CHIPS_BY_BUCKET[bucket] ?? CHIPS_BY_BUCKET.weekday

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  // 用户点 ✕ 撤掉约束后, 输入框里的草稿也要跟着清掉, 否则会残留一句已经作废的话
  useEffect(() => {
    if (!utterance) setDraft('')
  }, [utterance])

  const echo = useMemo(() => (intent?.understood ? intent.echo : []), [intent])

  /** 解析并落到 store。understood=false 与请求失败走同一条路: 当没听见 */
  const apply = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) {
      setUtterance('', null)
      return
    }
    setUtterance(trimmed, null)
    try {
      const parsed = await understandUtterance({ utterance: trimmed })
      if (parsed?.understood) {
        setUtterance(trimmed, { understood: true, echo: echoOf(parsed) })
      }
    } catch {
      // 完全静默: 解析不出来就照常无条件决策
    }
  }

  const clear = () => {
    setDraft('')
    setUtterance('', null)
  }

  const echoLine = echo.length > 0 ? `听你的：${echo.join(' · ')}` : null

  return (
    <div className={`utterance utterance--${variant}`}>
      {!open ? (
        <button type="button" className="utterance-guide" onClick={() => setOpen(true)}>
          {echoLine ?? guide}
        </button>
      ) : (
        <div className="utterance-box">
          <input
            ref={inputRef}
            className="utterance-input"
            value={draft}
            placeholder={PLACEHOLDER}
            maxLength={200}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter') return
              e.preventDefault()
              void apply(draft)
            }}
          />
          <button type="button" className="utterance-send" onClick={() => void apply(draft)}>
            好了
          </button>
          <button type="button" className="utterance-close" onClick={() => setOpen(false)}>
            收起
          </button>
        </div>
      )}

      {open && (
        <div className="utterance-chips">
          {chips.map((chip) => (
            <button
              key={chip}
              type="button"
              className="utterance-chip"
              onClick={() => {
                setDraft(chip)
                void apply(chip)
              }}
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      {/*
        回显只在 understood=true 时渲染。understood=false 时这里什么都不生成 ——
        没听懂就当没听见, 比猜错之后再改用户的菜要好。
      */}
      {echoLine ? (
        <div className="utterance-echo">
          <span>{echoLine}</span>
          <button type="button" className="utterance-echo-x" onClick={clear}>
            ✕
          </button>
        </div>
      ) : null}
    </div>
  )
}

export default UtteranceInput
