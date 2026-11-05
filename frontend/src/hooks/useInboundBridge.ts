/**
 * 双向唤醒独立状态机 —— 参照 useMealAssistant.ts 的 epoch / lock 并发保护,
 * 但与既有 useMealAssistant / MealAssistantDialog 完全隔离、零改动。
 *
 * 红线:
 *  - 网页侧令牌只存「内存态」(模块级内存 + React useSyncExternalStore 订阅),
 *    绝不写 localStorage / sessionStorage / URL / 日志;
 *  - 助手侧令牌明文绝不进入前端内存态, 只在设置卡片里一次性显示;
 *  - 幂等 request_id (crypto.randomUUID()) 复用; uncertain 只查询不重发;
 *  - completed / proposed 后调 onUpdated() 刷新, 但绝不自动 accept;
 *  - 轮询间隔: view(task) 无 poll_after_ms 字段, 用固定 4 秒 (落在 3-6 秒区间)。
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { inboundBridgePending } from '@shared/inboundBridge'
import type { MealView } from '@shared/meal'
import {
  getTaskStatus, issuePair, postEvent,
  type InboundAdjustData, type InboundPairIssue,
  type InboundPairMeta, type InboundTaskView,
} from '../api/inboundBridge'
import { buildSignedEnvelope } from '../lib/inboundBridgeSign'

/** 轮询间隔: view() 不含 poll_after_ms, 用固定值落在约定 3-6 秒内 */
const POLL_INTERVAL_MS = 4000

/** 令牌对元数据提取: 绝不带入 web_token / assistant_token 明文 */
function toPairMeta(result: InboundPairIssue): InboundPairMeta {
  return {
    pair_id: result.pair_id,
    assistant_instance_id: result.assistant_instance_id,
    session_id: result.session_id,
    allowlist_version: result.allowlist_version,
    web_state: result.web_state,
    assistant_state: result.assistant_state,
    expires_at: result.expires_at,
  }
}

/**
 * 模块级内存态: 只存网页侧令牌与令牌对元数据, 供设置卡片与触发弹窗在同一 SPA
 * 会话内共享。页面刷新即丢失, 绝不落任何持久化存储。助手侧令牌明文从不进来。
 */
interface InboundMemory {
  webToken: string
  pair: InboundPairMeta | null
}

let memory: InboundMemory = { webToken: '', pair: null }
const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function getSnapshot(): InboundMemory {
  return memory
}

function setMemory(patch: Partial<InboundMemory>): void {
  memory = { ...memory, ...patch }
  listeners.forEach((listener) => listener())
}

/** 颁发后记住连接: 供设置卡片调用, 让弹窗能拿到绑定参数 */
export function rememberIssue(result: InboundPairIssue): void {
  setMemory({ webToken: result.web_token, pair: toPairMeta(result) })
}

/** 轮换 web 侧后更新内存中的网页侧令牌 */
export function setInboundWebToken(token: string): void {
  setMemory({ webToken: token })
}

export function useInboundBridge(view: MealView | null, onUpdated: () => Promise<void>) {
  // 共享内存态（网页侧令牌 / pair 元数据）, 只存内存
  const shared = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  const [job, setJob] = useState<InboundTaskView | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [checking, setChecking] = useState(false)

  // 并发保护: epoch 丢弃过期异步结果, lock 防重复提交, statusRequest 保护只查询,
  // request 保存幂等 payload（uncertain 时只查询不重发）, applied 防重复刷新。
  const epoch = useRef(0)
  const lock = useRef(false)
  const statusRequest = useRef(0)
  const request = useRef<InboundAdjustData | null>(null)
  const applied = useRef('')

  const setWebToken = useCallback((token: string) => setMemory({ webToken: token }), [])
  const setPair = useCallback((pair: InboundPairMeta | null) => setMemory({ pair }), [])

  /** 颁发令牌对: 明文由调用方一次性显示, 这里只把非敏感元数据 + 网页侧令牌存内存 */
  const issue = useCallback(async (): Promise<InboundPairIssue> => {
    const result = await issuePair()
    rememberIssue(result)
    return result
  }, [])

  // 在途任务轮询: 只查询不重发, 逐档刷新状态
  useEffect(() => {
    if (!job || !inboundBridgePending(job.status)) return
    const ticket = epoch.current
    const timer = window.setTimeout(() => {
      void getTaskStatus(job.task_id).then((next) => {
        if (ticket === epoch.current) { setJob(next); setError('') }
      }).catch((err: Error) => {
        if (ticket === epoch.current) setError(err.message)
      })
    }, POLL_INTERVAL_MS)
    return () => window.clearTimeout(timer)
  }, [job])

  // 完成 / 新方案已保存后刷新主视图（绝不自动 accept / complete）
  useEffect(() => {
    if (!job) return
    if ((job.status === 'completed' || job.status === 'proposed') && applied.current !== job.task_id) {
      applied.current = job.task_id
      void onUpdated()
    }
  }, [job, onUpdated])

  /** 只查询, 不重发: 用于 uncertain 态与手动刷新 */
  const checkStatus = useCallback(async () => {
    const id = request.current?.request_id ?? job?.task_id
    if (!id) { setError('没有可查询的调整，请先发送'); return }
    const ticket = ++statusRequest.current
    setChecking(true)
    try {
      const next = await getTaskStatus(id)
      if (ticket === statusRequest.current) {
        setJob(next); setError(''); setUncertain(false)
      }
    } catch (err) {
      if (ticket === statusRequest.current) setError((err as Error).message)
    } finally {
      if (ticket === statusRequest.current) setChecking(false)
    }
  }, [job])

  /** 发送（或 uncertain 时只查询）。幂等 request_id 复用, 4xx 才清 uncertain */
  const send = async () => {
    if (lock.current || !view || !draft.trim() || submitting
      || inboundBridgePending(job?.status ?? '')) return
    const token = shared.webToken
    const meta = shared.pair
    if (!token) { setError('请先输入网页侧令牌（在设置页「双向唤醒（新）」颁发后复制）'); return }
    if (!meta) { setError('缺少连接参数，请先在设置页颁发令牌对'); return }
    lock.current = true
    const ticket = ++epoch.current
    setSubmitting(true); setError('')
    const payload = request.current ?? {
      request_id: crypto.randomUUID(),
      instruction: draft.trim(),
      context: view.context,
      expected_revision: view.revision,
    }
    request.current = payload
    try {
      let next: InboundTaskView
      if (uncertain) {
        // 发送状态未确认: 只按幂等 id 查询, 绝不重新 POST /events
        next = await getTaskStatus(payload.request_id)
      } else {
        const envelope = await buildSignedEnvelope(
          {
            pair_id: meta.pair_id,
            direction: 'web_to_bridge',
            event_type: 'meal.adjust.requested',
            task_id: '',
            phase: '-',
            assistant_instance_id: meta.assistant_instance_id,
            session_id: meta.session_id,
          },
          // data 严格只有 4 个字段, 后端 AdjustRequestedData 是 extra="forbid"
          { ...payload },
          token,
        )
        next = await postEvent(envelope)
      }
      if (ticket === epoch.current) {
        setJob(next); setUncertain(false); request.current = null
      }
    } catch (err) {
      if (ticket !== epoch.current) return
      const httpStatus = (err as { status?: number }).status
      if (httpStatus && httpStatus < 500) {
        setError((err as Error).message)
        setUncertain(false); request.current = null
        if (httpStatus === 409) void onUpdated()
      } else {
        setUncertain(true)
        setError('发送状态尚未确认，请查询状态。不会自动重复发送，你的输入已保留。')
      }
    } finally {
      if (ticket === epoch.current) { setSubmitting(false); lock.current = false }
    }
  }

  /** 取消等待: 发 meal.adjust.cancelled 事件（网页侧签名, data={task_id}） */
  const cancel = async () => {
    const token = shared.webToken
    const meta = shared.pair
    const id = job?.task_id ?? request.current?.request_id
    if (lock.current || !id || !token || !meta) return
    lock.current = true
    const ticket = ++epoch.current
    setSubmitting(true)
    try {
      const envelope = await buildSignedEnvelope(
        {
          pair_id: meta.pair_id,
          direction: 'web_to_bridge',
          event_type: 'meal.adjust.cancelled',
          task_id: '',
          phase: '-',
          assistant_instance_id: meta.assistant_instance_id,
          session_id: meta.session_id,
        },
        { task_id: id },
        token,
      )
      const next = await postEvent(envelope)
      if (ticket === epoch.current) {
        setJob(next); setUncertain(false); setError(''); request.current = null
      }
    } catch (err) {
      if (ticket === epoch.current) setError((err as Error).message)
    } finally {
      if (ticket === epoch.current) { lock.current = false; setSubmitting(false) }
    }
  }

  return {
    job, draft, setDraft, error, setError, submitting, uncertain, checking,
    webToken: shared.webToken, pair: shared.pair,
    setWebToken, setPair, issue,
    pending: submitting || uncertain || inboundBridgePending(job?.status ?? ''),
    send, cancel, checkStatus,
  }
}
