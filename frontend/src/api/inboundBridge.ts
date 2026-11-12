/**
 * 双向唤醒模块 API 层 —— 路径全部取自 shared/endpoints.ts 的 ENDPOINTS 常量,
 * 不在前端硬编码任何字符串。完整路径 = apiClient 的 baseURL('/api') + 常量。
 *
 * 兼容资产（deprecated）：统一模式后本文件不再被挂载，保留供签名固定向量测试与旧调用方引用；不参与主流程。
 *
 * 成功响应统一 { code:0, message:'success', data: ... }, 用 unwrap<T>() 解包;
 * 错误由后端 problem() 抛 HTTPException, 沿用既有 apiClient 拦截器 / normalizeError。
 * 全部端点 Cache-Control: no-store（后端 no_store 依赖注入）。
 *
 * 令牌明文绝不作为 URL 参数或请求体字段出现: envelope 里只有 sig（64 位 hex）。
 */
import apiClient, { unwrap } from './client'
import { ENDPOINTS } from '@shared/endpoints'
import type { MealContext } from '@shared/meal'
import type { InboundEnvelope } from '../lib/inboundBridgeSign'

/** POST /pair 返回: 明文 web_token / assistant_token 只在此响应里出现一次 */
export interface InboundPairIssue {
  pair_id: string
  web_token: string
  assistant_token: string
  assistant_instance_id: string
  session_id: string
  allowlist_version: string
  web_state: string
  assistant_state: string
  expires_at: string
  message: string
}

/** POST /pair/{id}/rotate 返回: 新令牌明文只出现一次 */
export interface InboundRotateResult {
  pair_id: string
  side: string
  token: string
  allowlist_version: string
  web_state: string
  assistant_state: string
  grace_seconds: number
  rotated_at: string
  message: string
}

/** 令牌对状态元数据（绝不含令牌明文 / 密文 / 哈希） */
export interface InboundPairMeta {
  pair_id: string
  assistant_instance_id: string
  session_id: string
  allowlist_version: string
  web_state: string
  assistant_state: string
  expires_at: string
}

/** 任务状态视图, 逐字对齐 orchestrator.view() 的字段 */
export interface InboundTaskView {
  task_id: string
  user_id: number
  pair_id: string
  session_id: string
  assistant_instance_id: string
  event_type: string
  phase: string
  status: string
  instruction: string
  expected_revision: number
  message_id: string | null
  error: string | null
  proposal_id: string | null
  expires_at: string | null
  next_poll_at: string | null
  poll_failures: number
  created_at: string | null
}

/** GET /allowlist 返回 */
export interface InboundAllowlist {
  version: string
  events: {
    event_type: string
    enabled: boolean
    directions: string[]
    phases: string[]
    version: string
  }[]
  forbidden: string[]
  directions: string[]
  phases: string[]
  enabled: boolean
}

/** GET /audit 返回的单条记录（SAFE_FIELDS） */
export interface InboundAuditRow {
  event_id: string
  user_id: number
  pair_id: string | null
  task_id: string | null
  direction: string
  event_type: string
  outcome: string
  reason_code: string
  allowlist_version: string
  created_at: string | null
}

/** GET /poll 返回 */
export interface InboundPollResult {
  tasks: InboundTaskView[]
  version: string
}

/** meal.adjust.requested 的 data（全部 extra="forbid", 禁止 user_id） */
export interface InboundAdjustData {
  request_id: string
  instruction: string
  context: MealContext
  expected_revision: number
}

export type InboundSide = 'web' | 'assistant'

/** 颁发令牌对（网页登录 cookie）; 明文只出现这一次 */
export const issuePair = () =>
  unwrap<InboundPairIssue>(apiClient.post(ENDPOINTS.inboundBridgePair))

/** 单端轮换（网页登录 cookie） */
export const rotatePair = (id: string, side: InboundSide) =>
  unwrap<InboundRotateResult>(
    apiClient.post(ENDPOINTS.inboundBridgePairRotate(id), undefined, { params: { side } }),
  )

/** 单端撤销（网页登录 cookie） */
export const revokePair = (id: string, side: InboundSide) =>
  unwrap<{ revoked: boolean }>(
    apiClient.delete(ENDPOINTS.inboundBridgePairItem(id), { params: { side } }),
  )

/** 白名单枚举 + 版本 + 方向 + 阶段 + enabled */
export const getAllowlist = () =>
  unwrap<InboundAllowlist>(apiClient.get(ENDPOINTS.inboundBridgeAllowlist))

/** 仅自己的审计记录 */
export const getAudit = (limit = 50) =>
  unwrap<InboundAuditRow[]>(
    apiClient.get(ENDPOINTS.inboundBridgeAudit, { params: { limit } }),
  )

/** 只查询不重发（网页登录 cookie） */
export const getTaskStatus = (taskId: string) =>
  unwrap<InboundTaskView>(
    apiClient.get(ENDPOINTS.inboundBridgeStatus, { params: { task_id: taskId } }),
  )

/** 网页触发: POST /events, 请求体是网页侧签名 envelope */
export const postEvent = (envelope: InboundEnvelope) =>
  unwrap<InboundTaskView>(apiClient.post(ENDPOINTS.inboundBridgeEvents, envelope))

/** 助手侧拉取: 签名 envelope 放 X-Inbound-Envelope 请求头, 不进 URL 查询串 */
export const assistantPoll = (envelope: InboundEnvelope) =>
  unwrap<InboundPollResult>(
    apiClient.get(ENDPOINTS.inboundBridgePoll, {
      headers: { 'X-Inbound-Envelope': JSON.stringify(envelope) },
    }),
  )

/** 助手侧回执: 签名 envelope 放请求体, 不依赖网页 JWT */
export const postReceipt = (envelope: InboundEnvelope) =>
  unwrap<InboundTaskView>(apiClient.post(ENDPOINTS.inboundBridgeReceipts, envelope))
