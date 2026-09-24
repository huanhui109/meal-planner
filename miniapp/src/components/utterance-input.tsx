/**
 * 一句话诉求输入 (utterance) 小程序端
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
 *     用户的第一反应是"我是不是得填点什么", 那正好是反模式。
 *   - 有结果时挪到动作行旁边 —— 真实诉求大多在**看到候选之后**才产生。
 */
import { useState } from 'react'
import { Input, Text, View } from '@tarojs/components'

import { contextBucket } from '@shared/decide-context'
import { http } from '../lib/request'
import { track } from '../lib/track'

const PLACEHOLDER = '比如：清淡点，别太辣'

/** 引导语按时段换语气: 同一件事在不同时刻说法不同 */
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

export type UtteranceEcho = { understood: boolean; echo: string[] }

/** `/decide/understand` 的返回形状: 只解析不决策, 拿它做"我听懂了"的回显 */
type UnderstandPayload = {
  understood?: boolean
  require_light?: boolean
  max_spice?: number | null
  max_minutes?: number | null
  prefer_fridge?: boolean
  avoid_meat?: boolean
  category?: string | null
  avoid?: string[]
}

/** 把结构化意图翻译成给用户看的一行约束, 最多 3 个词 */
function echoOf(intent: UnderstandPayload): string[] {
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

export function UtteranceInput({
  variant = 'hero',
  /** 受控: 文本与"听懂了没有"由决策区持有 —— 主按钮文案也要用它 */
  utterance,
  echo,
  onChange,
}: {
  variant?: 'hero' | 'inline'
  utterance: string
  echo: UtteranceEcho | null
  onChange: (text: string, echo: UtteranceEcho | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(utterance)

  const bucket = contextBucket()
  const guide = GUIDE_BY_BUCKET[bucket] ?? GUIDE_BY_BUCKET.weekday
  const chips = CHIPS_BY_BUCKET[bucket] ?? CHIPS_BY_BUCKET.weekday

  /** 解析并回写。understood=false 与请求失败走同一条路: 当没听见 */
  const apply = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) {
      onChange('', null)
      return
    }
    onChange(trimmed, null)
    track('home_filter_tap', { filter: 'utterance', value: trimmed, result_count: 0 })
    try {
      const parsed = await http.post<UnderstandPayload>('/decide/understand', {
        utterance: trimmed,
      })
      if (parsed?.understood) {
        onChange(trimmed, { understood: true, echo: echoOf(parsed) })
      }
    } catch {
      // 完全静默: 解析不出来就照常无条件决策
    }
  }

  const clear = () => {
    setDraft('')
    onChange('', null)
  }

  const echoLine = echo?.understood && echo.echo.length > 0 ? `听你的：${echo.echo.join(' · ')}` : null

  return (
    <View className={`utterance utterance--${variant}`}>
      {!open ? (
        <Text className="utterance__guide" onClick={() => setOpen(true)}>
          {echoLine ?? guide}
        </Text>
      ) : (
        <View className="utterance__box">
          <Input
            className="utterance__input"
            value={draft}
            placeholder={PLACEHOLDER}
            maxlength={200}
            onInput={(e) => setDraft(e.detail.value)}
            onConfirm={() => void apply(draft)}
          />
          <Text className="utterance__send" onClick={() => void apply(draft)}>
            好了
          </Text>
          <Text className="utterance__close" onClick={() => setOpen(false)}>
            收起
          </Text>
        </View>
      )}

      {open ? (
        <View className="utterance__chips">
          {chips.map((chip) => (
            <Text
              key={chip}
              className="utterance__chip"
              onClick={() => {
                setDraft(chip)
                void apply(chip)
              }}
            >
              {chip}
            </Text>
          ))}
        </View>
      ) : null}

      {/* 回显只在 understood=true 时渲染; 没听懂就当没听见 */}
      {echoLine ? (
        <View className="utterance__echo">
          <Text className="utterance__echo-text">{echoLine}</Text>
          <Text className="utterance__echo-x" onClick={clear}>
            ✕
          </Text>
        </View>
      ) : null}
    </View>
  )
}

export default UtteranceInput
