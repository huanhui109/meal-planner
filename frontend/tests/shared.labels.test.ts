/** 文案字典: 两端用词必须一致, 且未知值要有兜底 */
import { describe, expect, it } from 'vitest'
import { categoryRank, mealLabel, weekdayLabel, WEEKDAY_LABELS } from '@shared/labels'

describe('标签字典', () => {
  it('餐次有中文名', () => {
    expect(mealLabel('breakfast')).toBe('早餐')
    expect(mealLabel('dinner')).toBe('晚餐')
  })

  it('未知餐次原样返回, 不显示 undefined', () => {
    expect(mealLabel('brunch')).toBe('brunch')
  })

  it('星期索引越界返回空串', () => {
    expect(weekdayLabel(0)).toBe('周一')
    expect(WEEKDAY_LABELS).toHaveLength(7)
    expect(weekdayLabel(9)).toBe('')
  })

  it('分类按固定顺序排, 未知分类排最后', () => {
    expect(categoryRank('蔬菜')).toBe(0)
    expect(categoryRank('蔬菜')).toBeLessThan(categoryRank('调味'))
    expect(categoryRank('进口奶酪')).toBeGreaterThan(categoryRank('调味'))
  })
})
