import { describe, expect, it } from 'vitest'
import {
  budgetUsedPercent,
  orderStatusText,
  orderSummaryText,
  takeoutAdvice,
  takeoutHeadline,
  timelineLabel,
  timelineTone,
} from '@shared/today'

describe('timelineTone / timelineLabel', () => {
  it('把后端的四种状态映射成三态视觉语义', () => {
    expect(timelineTone('sent')).toBe('ok')
    expect(timelineTone('pending')).toBe('pending')
    expect(timelineTone('skipped')).toBe('off')
    expect(timelineTone('failed')).toBe('failed')
  })

  it('未知状态降级成"未开启", 不会让页面崩', () => {
    expect(timelineTone('whatever')).toBe('off')
    expect(timelineLabel('whatever')).toBe('未知')
  })

  it('每种状态都有中文说法', () => {
    expect(timelineLabel('sent')).toBe('已完成')
    expect(timelineLabel('pending')).toBe('待触发')
    expect(timelineLabel('failed')).toBe('失败')
    expect(timelineLabel('skipped')).toBe('未开启')
  })
})

describe('orderSummaryText / orderStatusText', () => {
  const order = {
    reaches_min_order: false,
    topup_amount: 6.5,
    missing_count: 3,
    estimated_total: 13.5,
    unpriced_count: 1,
  }

  it('缺几样、多少钱、有没有未计价', () => {
    expect(orderSummaryText(order)).toBe('3 样缺口 · 参考价合计 ¥13.5 · 1 样未计价')
  })

  it('没有未计价时不多说一句', () => {
    expect(orderSummaryText({ ...order, unpriced_count: 0 })).toBe(
      '3 样缺口 · 参考价合计 ¥13.5',
    )
  })

  it('够起送时显示"够起送", 否则显示还差多少', () => {
    expect(orderStatusText(order)).toBe('差 ¥6.5')
    expect(orderStatusText({ ...order, reaches_min_order: true })).toBe('够起送')
  })
})

describe('takeoutHeadline / takeoutAdvice', () => {
  it('三档结论各有一句人话', () => {
    expect(takeoutHeadline('homemade')).toContain('自己做饭')
    expect(takeoutHeadline('takeout')).toContain('外卖')
    expect(takeoutHeadline('either')).toContain('差不多')
  })

  it('未知结论不抛异常', () => {
    expect(takeoutHeadline('???')).toBeTruthy()
    expect(takeoutAdvice('???')).toBeTruthy()
  })

  it('推荐自做时把省下的钱说清楚', () => {
    expect(takeoutAdvice('homemade', 12)).toBe('今晚推荐自做, 能省 ¥12')
    expect(takeoutAdvice('homemade', 0)).toBe('今晚推荐自做')
    expect(takeoutAdvice('takeout')).toBe('今晚推荐外卖')
  })
})

describe('budgetUsedPercent', () => {
  it('取整数百分比', () => {
    expect(budgetUsedPercent(28, 35)).toBe(80)
    expect(budgetUsedPercent(10, 3)).toBe(333)
  })

  it('没设预算时不当成"用完了"', () => {
    expect(budgetUsedPercent(28, null)).toBe(0)
    expect(budgetUsedPercent(28, 0)).toBe(0)
  })
})
