/**
 * 决策埋点 (小程序端) —— 与 H5 的 lib/track.ts 同一份契约
 *
 * 走后端现有的 `POST /api/events` 批量端点, 不新造接口:
 *   backend/app/api/events.py 已经支持批量 + 任意 event_name + properties(json)。
 *
 * 🔴 三个字段必须落在**请求体顶层**: session_id / decision_id / layout_version
 *   后端 event 表有独立的 session_id 列和 (session_id, received_at) 复合索引,
 *   走列才能被索引命中; 塞进 properties 的 JSON 里, J1 闭环率每次查询都要全表扫。
 *   (后端对 properties 里的同名键有回落取值, 那是双端改造期的历史包袱 ——
 *    这里不往 properties 里写, 那条回落分支才删得掉。)
 *
 * 三条纪律:
 *   1. 埋点永远不阻塞交互, 也不弹 toast —— 打点失败就该静悄悄失败
 *   2. 上报攒批, 避免一次决策打 6 个请求
 *   3. 所有 props 都是纯规则可算的, 不依赖任何模型准确率
 */
import Taro from '@tarojs/taro'

import { ENDPOINTS } from '@shared/endpoints'
import type { EventBatchAck, EventBatchItem } from '@shared/types'

import pkg from '../../package.json'
import { http } from './request'
import { getLayoutVersion } from './layout-version'

/**
 * 真实版本号, 直接读 package.json —— 与 miniapp/package.json 同源, 不会写死漂移。
 * 不能留空: 留空后端就写 'unknown', 按版本切片的分母没了。
 */
const APP_VERSION: string = pkg.version

export const DECIDE_EVENTS = [
  'home_view',
  'home_filter_tap',
  'decide_roll',
  'decide_result_shown',
  'decide_reroll',
  'decide_accept',
  'decide_view_steps',
  'decide_cook_start',
  'decide_cook_done',
  'decide_reject',
  'stubborn_shown',
] as const

export type DecideEventName = (typeof DECIDE_EVENTS)[number]

/**
 * 上报条目: 直接用 shared 的 EventBatchItem —— 它已经声明了顶层
 * session_id / decision_id / layout_version 三个字段, 客户端不要在端上再扩一层,
 * 否则两端契约会各长一份。
 */
export type TrackedEvent = EventBatchItem

/** 会话空闲超过 30 分钟算换一次会话: 用户把小程序挂在后台一夜, 不该算成同一次纠结 */
const SESSION_IDLE_MS = 30 * 60 * 1000
const SESSION_KEY = 'mp:decide-session:v1'
const FLUSH_DEBOUNCE_MS = 1200
const FLUSH_MAX_BATCH = 20

let sessionId: string | null = null
let lastActiveAt = 0

/**
 * UUIDv4。小程序运行时没有 crypto.randomUUID, 也不值得为它引一个依赖 ——
 * 埋点 id 只要求"够随机、不撞", 用 Math.random 拼 v4 格式即可。
 */
function uuidV4(): string {
  const bytes: number[] = []
  for (let i = 0; i < 16; i += 1) bytes.push(Math.floor(Math.random() * 256))
  // 版本号 nibble = 0100, 变体位 = 10xx (RFC 4122 §4.4), 与真 uuid 同形
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = bytes.map((b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function readStoredSession(): { id: string; at: number } | null {
  try {
    const raw = Taro.getStorageSync(SESSION_KEY)
    const parsed = typeof raw === 'string' ? (JSON.parse(raw) as unknown) : raw
    if (!parsed || typeof parsed !== 'object') return null
    const value = parsed as { id?: unknown; at?: unknown }
    if (typeof value.id !== 'string' || !value.id) return null
    return { id: value.id, at: typeof value.at === 'number' ? value.at : 0 }
  } catch {
    return null
  }
}

function writeStoredSession(id: string, at: number): void {
  try {
    Taro.setStorageSync(SESSION_KEY, JSON.stringify({ id, at }))
  } catch {
    // 存不下就用内存里的, 不影响打点
  }
}

/**
 * 当前会话 id。同一次"打开首页 → 定下来"内恒定; 空闲超 30 分钟换新。
 * 跨页面刷新要能续上(写 storage), 否则刷新一下就把一次决策切成两个会话, J1/J2 全算歪。
 */
export function currentSessionId(now: number = Date.now()): string {
  if (sessionId && now - lastActiveAt < SESSION_IDLE_MS) {
    lastActiveAt = now
    return sessionId
  }
  const stored = readStoredSession()
  if (stored && now - stored.at < SESSION_IDLE_MS) {
    sessionId = stored.id
    lastActiveAt = now
    return sessionId
  }
  sessionId = uuidV4()
  lastActiveAt = now
  writeStoredSession(sessionId, lastActiveAt)
  return sessionId
}

export type TrackProps = Record<string, unknown>

const queue: TrackedEvent[] = []
let flushTimer: ReturnType<typeof setTimeout> | null = null

function flush(): void {
  flushTimer = null
  if (!queue.length) return
  const batch = queue.splice(0, queue.length)
  // 会话的"最后活跃时间"跟着批次一起落盘: 进程被杀也能续上同一个会话
  if (sessionId) writeStoredSession(sessionId, lastActiveAt)
  // 埋点失败静默: 打点不该影响用户正在做的事
  http
    .post<EventBatchAck>(ENDPOINTS.events, { events: batch }, { skipAuthRedirect: true })
    .catch(() => undefined)
}

function scheduleFlush(): void {
  if (queue.length >= FLUSH_MAX_BATCH) {
    if (flushTimer) clearTimeout(flushTimer)
    flush()
    return
  }
  if (flushTimer) return
  flushTimer = setTimeout(flush, FLUSH_DEBOUNCE_MS)
}

/**
 * 打一个事件。session_id / layout_version 自动补, 调用方不用传。
 *
 * decision_id 走顶层: 它是"这次决策"的外键, 不是描述这次决策的属性,
 * 放在 properties 里既进不了索引也没法直接 join。
 */
export function track(event: DecideEventName | string, props: TrackProps = {}): void {
  const now = Date.now()
  const { decision_id: decisionId, ...rest } = props as TrackProps & {
    decision_id?: unknown
  }
  queue.push({
    event_name: event,
    ts: now,
    platform: 'weapp',
    // 与 H5 同一份 app_version 口径: 打包时的 package.json 版本,
    // 不能留空 —— 留空后端就写 'unknown', 按版本切片的分母没了
    app_version: APP_VERSION,
    session_id: currentSessionId(now),
    decision_id: typeof decisionId === 'number' ? decisionId : null,
    // ⚠ 拿不到服务端值时是 null, 不猜 —— 猜一个组会让灰度结论失效
    layout_version: getLayoutVersion(),
    properties: rest,
  })
  scheduleFlush()
}

/** 页面隐藏 / 卸载前把攒下的事件发出去, 否则退出小程序会丢最后几个 */
export function flushNow(): void {
  if (flushTimer) clearTimeout(flushTimer)
  flush()
}
