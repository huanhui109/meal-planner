/**
 * 订阅消息封装 (audit T2.2)
 *
 * 调起微信原生授权弹窗 → 把结果回传后端 → 持久化用户偏好
 *
 * 关键行为:
 * 1. 长期订阅只在前端按下 "总是同意" 才传 grant=true; 否则记 grant=false + accepted='accept'
 *    (一次性订阅 accepted=accept 后只能推送 1 次, 后端调度器据此判定)
 * 2. 用户拒绝 / 已 ban 后再调仍是 ban, 不要在 30 天内反复弹 (交给微信端处理)
 * 3. 失败降级: 弹窗异常 / 微信返回错都静默吞掉, 不影响业务
 */
import Taro from '@tarojs/taro'

import { grantSubscribe } from './api'

export type SubscribeDecision = 'accept' | 'deny' | 'ban' | 'cancel' | 'error'

interface RequestArgs {
  tmplIds: string[] // 微信一次最多 3 个
  /** 立即向后端回写结果 (默认 true) */
  reportToServer?: boolean
}

type TaroSubscribeOption = Parameters<typeof Taro.requestSubscribeMessage>[0]

/**
 * 调起原生授权弹窗并把结果回写后端
 * 返回每条 template 的最终决定 + 是否发生错误
 */
export async function requestSubscribe(
  args: RequestArgs,
): Promise<Record<string, SubscribeDecision>> {
  if (!Taro.requestSubscribeMessage) {
    // 老基础库 / H5 构建静默返回空
    return Object.fromEntries(args.tmplIds.map((id) => [id, 'error'])) as Record<string, SubscribeDecision>
  }
  const report = args.reportToServer !== false
  // Taro 的 AtLeastOne 类型要求 entityIds 必填 (支付宝字段, 微信忽略); 实际运行时只用 tmplIds
  const option = { tmplIds: args.tmplIds } as unknown as TaroSubscribeOption
  try {
    const result = await Taro.requestSubscribeMessage(option)
    // 微信一次只能原子问 1-3 个; 整体 ok 时都视为 accept
    const overall = (result as { errMsg?: string }).errMsg || ''
    const acceptedAll = overall.includes(':ok')

    const decisions: Record<string, SubscribeDecision> = {}
    for (const id of args.tmplIds) {
      const d: SubscribeDecision = acceptedAll ? 'accept' : 'deny'
      decisions[id] = d
      if (report) {
        try {
          await grantSubscribe({
            template_id: id,
            grant: d === 'accept',
            accepted: d,
          })
        } catch {
          /* 静默 — 同步失败不影响 UI */
        }
      }
    }
    return decisions
  } catch (err) {
    const msg = (err as { errMsg?: string })?.errMsg || ''
    let decision: SubscribeDecision = 'error'
    if (msg.includes('ban')) decision = 'ban'
    else if (msg.includes('deny') || msg.includes('cancel')) decision = 'deny'
    const decisions: Record<string, SubscribeDecision> = {}
    for (const id of args.tmplIds) {
      decisions[id] = decision
      if (report && decision !== 'error') {
        try {
          await grantSubscribe({ template_id: id, grant: false, accepted: decision })
        } catch {
          /* ignore */
        }
      }
    }
    return decisions
  }
}
