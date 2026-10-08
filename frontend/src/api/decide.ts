/**
 * 饭决决策接口
 *
 * 这里刻意做得"薄": 前端不该在决策这件事上做任何计算, 只负责把结果画出来。
 * 唯一的例外是 offline —— 断网时没有后端可用, 只能落到 shared/decide.ts。
 */
import apiClient, { unwrap } from './client'
import type {
  DecideFeedbackRequest,
  DecideProfile,
  DecideRecentItem,
  DecideRequest,
  DecisionResult,
} from '../types'

/**
 * 请求体比 shared 的 DecideRequest 多一个 utterance。
 *
 * 后端早就支持 (POST /decide 的 utterance 走 Laya 把口语变成结构化意图,
 * 只做减法过滤 + 小幅加分, 绝不进打分排序), 前端一直没接入口。
 * 这里不往 shared/types.ts 加字段是为了避免和小程序端同改一个文件冲突 ——
 * 小程序端随后对齐时会自己补上, 届时把这段交集类型收回 shared。
 */
export type DecidePayload = DecideRequest & { utterance?: string }

/** `/decide/understand` 的返回: 只解析不决策, 前端拿它做"我听懂了"的回显 */
export interface UnderstandResult {
  utterance: string
  source?: string
  understood: boolean
  confidence?: number
  intent_type?: string
  require_light?: boolean
  max_spice?: number | null
  max_minutes?: number | null
  prefer_fridge?: boolean
  avoid_meat?: boolean
  cuisine?: string | null
  category?: string | null
  avoid?: string[]
}

/**
 * /decide 的超时: 2500ms
 *
 * 为什么不能用 client.ts 那个全局 30 秒 —— 那 30 秒是给**异步生成任务**留的
 * (周菜单生成要 1-2 分钟, 前端靠轮询等), 和决策根本不是一回事:
 *   - 决策是对外承诺 ≤2 秒的同步链路: 2 秒是"定这一顿"这个主张能不能成立的上限,
 *     超过就不是"慢一点", 是主张失效
 *   - 2500 = 2 秒承诺 + 500ms 网络抖动余量
 *   - 超时即走 roll() 的 catch → 本地候选池, 打「本地答案」角标。本地池 1 秒内
 *     就能算出答案, 让用户等 30 秒去拿一个本地 1 秒能算出的东西, 比拿不到还糟
 *   - 更糟的是加载态: 首屏 <1200ms 不显示"正在替你决定", 1200ms 之后显示 ——
 *     30 秒超时意味着用户要盯着那行字看满 28 秒, 会以为卡死
 *
 * 断网是秒级失败(请求直接 reject), 真正被这行救下的是"服务端慢 / 半死不活"那一档。
 */
const DECIDE_TIMEOUT_MS = 2500

/**
 * 决定这一顿吃什么。utterance 不传(或空串)就是完全无条件决策。
 *
 * ⚠ 超时抛的是 axios 的 ECONNABORTED, 与普通网络错误一样是 rejected promise,
 * 会被 useDecideStore.roll() 的 catch 接住并走离线兜底(不是当真错误弹提示)。
 */
export const decide = (payload: DecidePayload = {}) =>
  unwrap<DecisionResult>(
    apiClient.post('/decide', payload, { timeout: DECIDE_TIMEOUT_MS }),
  )

/**
 * 把一句口语解析成结构化诉求。只解析不决策。
 *
 * 调用方必须容忍失败: 超时/异常一律静默, 连 toast 都不弹 ——
 * 它只是给用户一个"我被听见了"的确认, 不该为它打断决策。
 */
export const understandUtterance = (payload: {
  utterance: string
  meal_slot?: string
  fridge?: string[]
}) => unwrap<UnderstandResult>(apiClient.post('/decide/understand', payload))

/** 上一次决策快照 —— 冷启动秒开, 避免首屏闪一下空卡 */
export const getLastDecision = () =>
  unwrap<DecisionResult | null>(apiClient.get('/decide/last'))

/** 决策所需的压缩档案: 口味 + 忌口 + 时段 + 天气 */
export const getDecideProfile = () => unwrap<DecideProfile>(apiClient.get('/decide/profile'))

export const getRecentDecisions = (days = 7) =>
  unwrap<DecideRecentItem[]>(apiClient.get('/decide/recent', { params: { days } }))

export const sendDecideFeedback = (decisionId: number, liked: boolean) =>
  unwrap<{ accepted: boolean }>(
    apiClient.post(`/decide/${decisionId}/feedback`, { liked } as DecideFeedbackRequest),
  )

/** 今日饭决「做完了」: 按结果菜谱扣减冰箱库存 (2.7.0) */
export const cookDecision = (decisionId: number) =>
  unwrap<{
    decision_id: number
    already_cooked: boolean
    no_recipe?: boolean
    consumed: Array<{ ingredient_name: string; quantity: number; unit: string }>
    missing: Array<{ ingredient_name: string; quantity: number; unit: string }>
  }>(apiClient.post(`/decide/${decisionId}/cook`))
