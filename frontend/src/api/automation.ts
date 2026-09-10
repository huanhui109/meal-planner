import apiClient, { unwrap } from './client'
import { ENDPOINTS } from '@shared/endpoints'
import type { AutomationStatus, FeishuConfigInput, FeishuConfigView } from '../types'

/** 飞书机器人连接状态 + 定时推送配置 + 最近推送记录 */
export const getAutomationStatus = () =>
  unwrap<AutomationStatus>(apiClient.get(ENDPOINTS.automationStatus))

/** 当前用户生效的飞书配置 (App Secret 只回掩码) */
export const getFeishuConfig = () =>
  unwrap<FeishuConfigView>(apiClient.get(ENDPOINTS.automationFeishu))

/** 保存自己的飞书应用凭证; app_secret 留空表示沿用已保存的密钥 */
export const saveFeishuConfig = (payload: FeishuConfigInput) =>
  unwrap<FeishuConfigView>(apiClient.put(ENDPOINTS.automationFeishu, payload))

/** 清除个人配置, 回落到部署默认 */
export const deleteFeishuConfig = () =>
  unwrap<null>(apiClient.delete(ENDPOINTS.automationFeishu))

/** 用当前配置发一条测试消息, 立刻知道参数对不对 */
export const testFeishuConfig = () =>
  unwrap<{ ok: boolean; message: string }>(apiClient.post(ENDPOINTS.automationFeishuTest))
