/**
 * 决策埋点 —— 全站唯一的事件出口
 *
 * 为什么必须有 session_id 而且是前端生成:
 *   首轮成决策率(DCR)和"换一个次数中位数"这两个北极星指标, 分母都是**会话**不是决策。
 *   后端一次决策一行日志, 没有会话概念, 后端自己也拼不出来 —— 只有前端知道
 *   "打开首页 → 定下来"这段是不是同一次。所以 session_id 必须在进首页时生成,
 *   同一段过程内贯穿所有事件。
 *
 * 为什么走 /events 而不是新接口:
 *   backend/app/api/events.py 已经支持批量 + 任意 event_name + properties(json),
 *   够用。后端另一个 worker 正在做 decision_event 表与专用上报接口,
 *   本版先把 11 个判据事件打到统一出口, 等专用接口就绪后只需换 track() 里的落点。
 *
 * 三条纪律:
 *   1. 埋点永远不阻塞交互, 也不弹 toast —— 打点失败就该静悄悄失败
 *   2. 上报走批量攒批, 避免一次决策打 6 个请求
 *   3. 所有 props 都是纯规则可算的, 不依赖任何模型准确率
 */
import { reportEvents } from '../api/events'
import { APP_VERSION } from './app-version'
import { getLayoutVersion } from './layout-version'
import type { EventBatchItem } from '../types'

/**
 * home_filter_tap 已经从 PRD 的事件清单里删除(v1.6, 12 → 11):
 *   新首页没有筛选格子, 全站找不到一个语义成立的触发点, 唯一能挂的是冰箱快选
 *   chip, 但那是"录入食材"不是"筛选", 硬凑出来的数据不能当判据。
 *
 * 它**仍在这个数组里、仍在打点**, 原因是拆掉打点要动 store 且没有任何收益;
 * 但按 PRD v1.6 的规定: **它不得作为任何指标的数据源**。看到这里的人不要再为它
 * 找触发点、也不要拿它算数 —— 判据已经换成后端 decision_log.candidate_count。
 */
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

/** 会话空闲超过 30 分钟算换一次会话: 用户把 App 挂在后台一夜, 不该算成同一次纠结 */
const SESSION_IDLE_MS = 30 * 60 * 1000
const SESSION_KEY = 'meal-planner:decide-session:v1'
const FLUSH_DEBOUNCE_MS = 1200
const FLUSH_MAX_BATCH = 20

let sessionId = ''
let lastActiveAt = 0

function uuidV4(): string {
  const cryptoRef = globalThis.crypto
  if (cryptoRef && typeof cryptoRef.randomUUID === 'function') return cryptoRef.randomUUID()
  // 老浏览器没有 randomUUID: 退到 getRandomValues 拼一个 v4, 够用且不引入依赖
  if (cryptoRef && typeof cryptoRef.getRandomValues === 'function') {
    const bytes = cryptoRef.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function readStoredSession(): { id: string; at: number } | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { id?: string; at?: number }
    if (!parsed.id) return null
    return { id: parsed.id, at: parsed.at ?? 0 }
  } catch {
    return null
  }
}

function writeStoredSession(id: string, at: number): void {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ id, at }))
  } catch {
    // 存不下就用内存里的, 不影响打点
  }
}

/**
 * 当前会话 id。同一次"打开首页 → 定下来"内恒定; 空闲超 30 分钟换新。
 * 跨页面刷新要能续上, 否则刷新一下就把一次决策切成两个会话, J1/J2 全算歪。
 *
 * 内存中的 sessionId 是**权威值**, localStorage 只负责跨刷新续上:
 *   隐私模式 / 存储被禁 / 配额满时 localStorage 会静默失败。如果只认存储,
 *   那台设备上每个事件都会拿到一个新 uuid —— 会话数等于事件数, J1 闭环率
 *   直接算成 0, 而且没有任何报错。宁可掉"跨刷新续上", 也不能掉"页内恒定"。
 *
 * 每次取用都把 at 刷成当前时间: 判据是"空闲 30 分钟", 不是"创建后 30 分钟"。
 * 不刷新的话, 一个连续用了 40 分钟的人会被切成两个会话。
 */
export function currentSessionId(now: number = Date.now()): string {
  if (sessionId && now - lastActiveAt < SESSION_IDLE_MS) {
    lastActiveAt = now
    writeStoredSession(sessionId, now)
    return sessionId
  }
  const stored = readStoredSession()
  sessionId = stored && now - stored.at < SESSION_IDLE_MS ? stored.id : uuidV4()
  lastActiveAt = now
  writeStoredSession(sessionId, now)
  return sessionId
}

export type TrackProps = Record<string, unknown>

const queue: EventBatchItem[] = []
let flushTimer: ReturnType<typeof setTimeout> | null = null

function flush(): void {
  flushTimer = null
  if (!queue.length) return
  const batch = queue.splice(0, queue.length)
  // 埋点失败静默: 打点不该影响用户正在做的事
  reportEvents(batch).catch(() => undefined)
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
 * 打一个事件。session_id / layout_version / app_version 自动补, 调用方不用传。
 *
 * 三个字段全部走**请求体顶层**而不是塞进 properties:
 *   session_id      —— 后端有独立列 + (session_id, received_at) 复合索引,
 *                      J1 闭环率的分母是会话数, 走列才能被索引命中。
 *   layout_version  —— 后端有独立列 (迁移 0019), M5 灰度发布靠它切片。
 *   app_version     —— 独立列, 不能留空, 留空后端就写 'unknown'。
 * 后端对 properties 里的同名键有回落取值(双端改造期用), 所以这里**不再往
 * properties 里写**, 否则那两条回落分支永远删不掉。
 */
export function track(event: DecideEventName | string, props: TrackProps = {}): void {
  const now = Date.now()
  const { decision_id: decisionId, ...rest } = props as TrackProps & {
    decision_id?: unknown
  }
  queue.push({
    event_name: event,
    ts: now,
    platform: 'h5',
    // R-16a: 真实版本号。不能留空 —— 留空后端就写 'unknown', 按版本切片的分母没了
    app_version: APP_VERSION,
    session_id: currentSessionId(now),
    decision_id: typeof decisionId === 'number' ? decisionId : null,
    // 与 session_id 同款: 走顶层列。拿不到服务端值时 getLayoutVersion() 返回 null,
    // 就老老实实记 NULL —— 替用户填一个分组, 灰度结论就是假的
    layout_version: getLayoutVersion(),
    properties: rest,
  })
  scheduleFlush()
}

/** 页面隐藏 / 卸载前把攒下的事件发出去, 否则关页面会丢最后几个 */
export function flushNow(): void {
  if (flushTimer) clearTimeout(flushTimer)
  flush()
}

/** 测试用: 清空队列与会话, 避免用例之间互相污染 */
export function __resetForTest(): void {
  queue.length = 0
  if (flushTimer) clearTimeout(flushTimer)
  flushTimer = null
  sessionId = ''
  lastActiveAt = 0
}
