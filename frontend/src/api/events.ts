/**
 * 埋点批量上报 (T2.6)
 *
 * 后端 /events 是 fire-and-forget 设计: 不鉴权、语法不对也静默接受。
 * 埋点失败绝不能影响主流程, 所以这里调用方一律不 await。
 */
import apiClient, { unwrap } from './client'
import type { EventBatchAck, EventBatchItem } from '../types'

export const reportEvents = (events: EventBatchItem[]) =>
  unwrap<EventBatchAck>(apiClient.post('/events', { events }))
