import { describe, expect, it } from 'vitest'
import {
  DISH_CATEGORIES,
  DISH_CATEGORY_CODES,
  DISH_CATEGORY_LABELS,
  DISH_CATEGORY_OTHER,
  detectDishCategoryMix,
  dishCategoryLabel,
  isDishCategoryCode,
} from '@shared/dish-category'

describe('菜品类别法典', () => {
  it('五类互斥、code 唯一、标签齐全', () => {
    expect(DISH_CATEGORY_CODES).toEqual([
      'chinese', 'western', 'japanese_korean', 'southeast_asian', 'other',
    ])
    expect(new Set(DISH_CATEGORY_CODES).size).toBe(5)
    expect(new Set(DISH_CATEGORIES.map((item) => item.label)).size).toBe(5)
    expect(DISH_CATEGORY_LABELS.chinese).toBe('中餐')
    expect(DISH_CATEGORY_LABELS.western).toBe('西餐')
    expect(DISH_CATEGORY_OTHER).toBe('other')
  })

  it('排序连续且从 1 开始', () => {
    expect(DISH_CATEGORIES.map((item) => item.sort_order)).toEqual([1, 2, 3, 4, 5])
  })

  it('只认法典里的 code', () => {
    expect(isDishCategoryCode('western')).toBe(true)
    expect(isDishCategoryCode('川菜')).toBe(false)
    expect(isDishCategoryCode(null)).toBe(false)
    expect(isDishCategoryCode('')).toBe(false)
    expect(dishCategoryLabel('japanese_korean')).toBe('日韩')
    expect(dishCategoryLabel(null)).toBe('未分类')
  })
})

describe('方案类别一致性判定', () => {
  it('单一类别或空方案通过', () => {
    expect(detectDishCategoryMix(['chinese', 'chinese', 'chinese'])).toBe('none')
    expect(detectDishCategoryMix(['western'])).toBe('none')
    expect(detectDishCategoryMix([])).toBe('none')
    expect(detectDishCategoryMix([null, 'chinese', undefined])).toBe('none')
  })

  it('中餐与西餐混排单独识别为最高风险', () => {
    expect(detectDishCategoryMix(['chinese', 'western'])).toBe('chinese_western')
    expect(detectDishCategoryMix(['western', 'chinese', 'other'])).toBe('chinese_western')
  })

  it('其它跨类别也算混搭', () => {
    expect(detectDishCategoryMix(['chinese', 'japanese_korean'])).toBe('mixed')
    expect(detectDishCategoryMix(['western', 'southeast_asian'])).toBe('mixed')
    expect(detectDishCategoryMix(['chinese', 'other'])).toBe('mixed')
  })
})
