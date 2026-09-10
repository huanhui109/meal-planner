/**
 * 今日页的展示逻辑 (纯函数)
 *
 * 为什么放在共享层: "这条日志算成功还是待触发""外卖到底推荐哪个"这类判断,
 * H5 与小程序必须给出**一模一样**的结论, 所以不能各写一份 if。
 * 真正的计算在后端 (order_service / takeout_service), 这里只做展示映射。
 */
import { formatMoney } from './format'

export type TimelineTone = 'ok' | 'pending' | 'failed' | 'off'

/** 时间线三态 -> 视觉语义 (绿=完成, 灰=待触发, 灰字=未开启, 红=失败) */
export const TIMELINE_TONES: Record<string, TimelineTone> = {
  sent: 'ok',
  pending: 'pending',
  skipped: 'off',
  failed: 'failed',
}

export function timelineTone(status: string): TimelineTone {
  return TIMELINE_TONES[status] ?? 'off'
}

/** 时间线状态的中文说法 */
export function timelineLabel(status: string): string {
  switch (status) {
    case 'sent':
      return '已完成'
    case 'pending':
      return '待触发'
    case 'failed':
      return '失败'
    case 'skipped':
      return '未开启'
    default:
      return '未知'
  }
}

export interface OrderLike {
  reaches_min_order: boolean
  topup_amount: number
  missing_count: number
  estimated_total: number
  unpriced_count: number
}

/** 补单卡的副标题: 缺几样、多少钱、有没有未计价的 */
export function orderSummaryText(order: OrderLike): string {
  const parts = [`${order.missing_count} 样缺口`, `参考价合计 ${formatMoney(order.estimated_total)}`]
  if (order.unpriced_count > 0) parts.push(`${order.unpriced_count} 样未计价`)
  return parts.join(' · ')
}

/** 补单卡右上角的状态胶囊: 够起送 / 还差多少 */
export function orderStatusText(order: OrderLike): string {
  if (order.reaches_min_order) return '够起送'
  return `差 ${formatMoney(order.topup_amount)}`
}

export type TakeoutVerdict = 'homemade' | 'takeout' | 'either'

/** 自做 vs 外卖的结论头一句 */
export function takeoutHeadline(recommended: TakeoutVerdict | string): string {
  switch (recommended) {
    case 'homemade':
      return '算下来自己做饭更划算'
    case 'takeout':
      return '今天点外卖反而更便宜'
    case 'either':
      return '两边差不多, 看你想不想动手'
    default:
      return '按你的参考价估个大概'
  }
}

/** 结论对应的一句话建议 (给不知道选哪个的人一个默认答案) */
export function takeoutAdvice(recommended: TakeoutVerdict | string, saving?: number | null): string {
  if (recommended === 'homemade') {
    return saving && saving > 0 ? `今晚推荐自做, 能省 ${formatMoney(saving)}` : '今晚推荐自做'
  }
  if (recommended === 'takeout') return '今晚推荐外卖'
  return '今晚随意, 看时间安排'
}

/** 今天预算条: 已用百分比 (整数, 超过 100 也如实显示) */
export function budgetUsedPercent(spent: number, limit: number | null | undefined): number {
  if (!limit || limit <= 0) return 0
  return Math.round((spent / limit) * 100)
}
