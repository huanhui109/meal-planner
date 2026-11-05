/**
 * 饭决双向唤醒模块 (fandecide_inbound_bridge) 的唯一真源。
 *
 * 这里只放常量与纯函数, 不依赖 React / Taro / Node。后端
 * `backend/app/services/inbound_bridge/allowlist.py` 会**独立硬编码同一份枚举**做
 * 服务端校验, 不 import 本文件 —— 前端传来的枚举值永远不被信任。
 * 改这里的枚举必须同步改后端 allowlist.py, 否则会出现"前端能发、后端拒绝"的分叉。
 *
 * 本文件是手写源文件, 不是 scripts/gen_tokens.mjs 的生成产物。
 */

/** 白名单版本: 前后端必须一致, 版本不匹配一律拒绝 */
export const INBOUND_ALLOWLIST_VERSION = 'ib-1.0'
/** envelope 协议版本 v */
export const INBOUND_PROTOCOL_VERSION = 1

export const INBOUND_DIRECTIONS = [
  'web_to_bridge',
  'assistant_to_bridge',
  'bridge_to_assistant',
] as const
export type InboundDirection = (typeof INBOUND_DIRECTIONS)[number]

export const INBOUND_PHASES = ['-', 'context', 'proposal'] as const
export type InboundPhase = (typeof INBOUND_PHASES)[number]

export const INBOUND_EVENT_TYPES = [
  'meal.adjust.requested',
  'meal.adjust.cancelled',
  'meal.adjust.status_queried',
  'assistant.context_replied',
  'assistant.proposal_replied',
  'assistant.failed',
  'pair.status_queried',
  'pair.connection_managed',
  'task.status_queried',
] as const
export type InboundEventType = (typeof INBOUND_EVENT_TYPES)[number]

export interface InboundEventPolicy {
  enabled: boolean
  directions: readonly InboundDirection[]
  phases: readonly InboundPhase[]
}

/**
 * 显式事件白名单。P0 五类全开; P1 三类登记为枚举但默认 disabled。
 * 未出现在这里的事件一律默认拒绝, 不会降级成 prompt 指令。
 */
export const ALLOWED_EVENTS: Record<InboundEventType, InboundEventPolicy> = {
  'meal.adjust.requested': { enabled: true, directions: ['web_to_bridge'], phases: ['-'] },
  'meal.adjust.cancelled': { enabled: true, directions: ['web_to_bridge'], phases: ['-'] },
  'meal.adjust.status_queried': { enabled: true, directions: ['web_to_bridge'], phases: ['-'] },
  'assistant.context_replied': { enabled: true, directions: ['assistant_to_bridge'], phases: ['context'] },
  'assistant.proposal_replied': { enabled: true, directions: ['assistant_to_bridge'], phases: ['proposal'] },
  'assistant.failed': { enabled: true, directions: ['assistant_to_bridge'], phases: ['context', 'proposal'] },
  'pair.status_queried': { enabled: false, directions: ['web_to_bridge'], phases: ['-'] },
  'pair.connection_managed': { enabled: false, directions: ['web_to_bridge'], phases: ['-'] },
  'task.status_queried': { enabled: false, directions: ['web_to_bridge'], phases: ['-'] },
}

/**
 * 永久禁止清单。硬编码, 不提供任何配置键, 不因白名单收紧/放开而改变。
 * 后端 allowlist.py 独立硬编码同一份, 命中即 403。
 */
export const FROZEN_FORBIDDEN = [
  'order.*',
  'payment.*',
  'meal.accept',
  'meal.complete',
  'meal.undo',
  'inventory.deduct',
  'message.send_external',
  'preference.write',
  'restriction.write',
  'tool.execute',
  'cli.execute',
  'url.fetch_arbitrary',
  'credential.read',
  'conversation.read_other',
  'approval.answer_on_behalf',
  'event.unlisted',
] as const

export const INBOUND_TASK_STATUSES = [
  'received',
  'waking',
  'awaiting_assistant',
  'awaiting_user_approval',
  'validating',
  'proposed',
  'completed',
  'rejected',
  'offline',
  'timed_out',
  'uncertain',
  'conflict',
  'failed',
  'cancelled',
  'disconnected',
] as const
export type InboundTaskStatus = (typeof INBOUND_TASK_STATUSES)[number]

/** 在途状态: 只有这些能被取消/超时; 其余都是终止态 */
export const INBOUND_ACTIVE_STATUSES = [
  'received',
  'waking',
  'awaiting_assistant',
  'awaiting_user_approval',
  'validating',
  'uncertain',
] as const

export const inboundBridgePending = (status: string): boolean =>
  (INBOUND_ACTIVE_STATUSES as readonly string[]).includes(status)

export const INBOUND_TOKEN_STATES = ['issued', 'active', 'rotated', 'revoked', 'expired'] as const
export type InboundTokenState = (typeof INBOUND_TOKEN_STATES)[number]

export const INBOUND_OUTCOMES = ['allowed', 'rejected', 'rotated', 'revoked', 'state_change'] as const
export type InboundOutcome = (typeof INBOUND_OUTCOMES)[number]

/** 只给可读中文文案; 内部细节与令牌一律不进响应 */
export const INBOUND_ERROR_CODES = {
  OK: 0,
  TOKEN_INVALID: 1401,
  NOT_ALLOWLISTED: 1403,
  NOT_FOUND: 1404,
  CONFLICT: 1409,
  INVALID_SCHEMA: 1422,
  RATE_LIMITED: 1429,
  DISABLED: 1503,
} as const
export type InboundErrorCode = (typeof INBOUND_ERROR_CODES)[keyof typeof INBOUND_ERROR_CODES]

const STATUS_LABELS: Record<InboundTaskStatus, string> = {
  received: '已收到请求，正在校验',
  waking: '正在唤醒本机助手',
  awaiting_assistant: '等待助手回执；原方案未改变',
  awaiting_user_approval: '助手可能正在等待你确认工具操作，请在 WorkBuddy 中查看',
  validating: '正在复核助手建议；原方案未改变',
  proposed: '新方案已保存，等你决定',
  completed: '已完成',
  rejected: '请求被拒绝；原方案未改变',
  offline: '助手当前离线，请打开电脑上的助手，或复制任务',
  timed_out: '等待助手超时，原方案未改变',
  uncertain: '发送状态尚未确认，请查询状态。不会自动重复发送',
  conflict: '这一餐已在另一处更新，已保留最新方案，请刷新后再试',
  failed: '本次调整未成功，原方案未改变',
  cancelled: '已取消等待，本次回复不会保存',
  disconnected: '连接已断开，本次调整不会保存',
}

/** 逐档如实告知, 不把异常说成成功 */
export function inboundBridgeLabel(status: string): string {
  return STATUS_LABELS[status as InboundTaskStatus] ?? '状态未知，请刷新后查询'
}
