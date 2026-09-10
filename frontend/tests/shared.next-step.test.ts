/**
 * "下一步该做什么"决策的回归测试
 *
 * 首页的指引卡、各页空状态都读这里, H5 与小程序共用同一份规则, 所以优先级
 * 一旦改了这里会立刻红。优先级 (从高到低):
 *   生成中 > 没偏好 > 没菜单 > 草稿未确认 > 有食材要买 > 今天还有饭要做 > 歇着
 */
import { describe, expect, it } from 'vitest'
import { nextStep, remainingMealsToday, type NextStepInput, type NextStepMenuLike } from '@shared/next-step'

const TODAY = '2026-09-10'

function makeMenu(overrides: Partial<NextStepMenuLike> = {}): NextStepMenuLike {
  return {
    status: 'confirmed',
    week_start_date: '2026-09-07',
    totals: { cooked_count: 10, meal_count: 14 },
    days: [
      { date: TODAY, meals: [{ is_cooked: true }, { is_cooked: false }] },
      { date: '2026-09-11', meals: [{ is_cooked: false }] },
    ],
    ...overrides,
  }
}

function input(overrides: Partial<NextStepInput> = {}): NextStepInput {
  return {
    hasPreferences: true,
    menu: makeMenu(),
    shoppingToBuyCount: 0,
    today: TODAY,
    ...overrides,
  }
}

describe('nextStep 优先级', () => {
  it('生成中排最前, 即使偏好没填完', () => {
    const step = nextStep(input({ generating: true, hasPreferences: false, menu: null }))
    expect(step.key).toBe('generating')
    expect(step.actionLabel).toBeNull()
  })

  it('没填偏好 -> 去填偏好', () => {
    const step = nextStep(input({ hasPreferences: false, menu: null }))
    expect(step.key).toBe('setup-preferences')
    expect(step.to).toBe('/preferences')
  })

  it('有偏好但没菜单 -> 原地生成 (不跳页)', () => {
    const step = nextStep(input({ menu: null }))
    expect(step.key).toBe('generate-menu')
    expect(step.isGenerateAction).toBe(true)
    expect(step.to).toBeNull()
    expect(step.actionLabel).toBe('生成菜单')
  })

  it('草稿未确认优先于采购, 只有确认了清单才作数', () => {
    const step = nextStep(input({ menu: makeMenu({ status: 'draft' }), shoppingToBuyCount: 5 }))
    expect(step.key).toBe('confirm-menu')
    expect(step.to).toBe('/menus')
  })

  it('有待买食材 -> 采购清单, 并把数量写进标题', () => {
    const step = nextStep(input({ shoppingToBuyCount: 4 }))
    expect(step.key).toBe('shopping')
    expect(step.title).toContain('4')
    expect(step.to).toBe('/shopping')
  })

  it('今天还有没做的餐 -> 去周菜单, 描述里带本周进度', () => {
    const step = nextStep(input())
    expect(step.key).toBe('cook-today')
    expect(step.description).toContain('10/14 餐')
    expect(step.to).toBe('/menus')
  })

  it('今天都做完了 -> 进入放松态', () => {
    const menu = makeMenu({
      totals: { cooked_count: 14, meal_count: 14 },
      days: [{ date: TODAY, meals: [{ is_cooked: true }, { is_cooked: true }] }],
    })
    const step = nextStep(input({ menu }))
    expect(step.key).toBe('relax')
    expect(step.description).toContain('9月7日')
  })

  it('菜单里没有今天 (下周的菜单) 也算没饭要做', () => {
    const menu = makeMenu({ days: [{ date: '2026-09-20', meals: [{ is_cooked: false }] }] })
    expect(nextStep(input({ menu })).key).toBe('relax')
  })
})

describe('remainingMealsToday', () => {
  it('只数今天且没标记已做的餐', () => {
    expect(remainingMealsToday(input())).toBe(1)
  })

  it('没有菜单时为 0', () => {
    expect(remainingMealsToday(input({ menu: null }))).toBe(0)
  })
})

describe('每条指引都是一句话 + 最多一个按钮', () => {
  const cases: NextStepInput[] = [
    input({ generating: true }),
    input({ hasPreferences: false }),
    input({ menu: null }),
    input({ menu: makeMenu({ status: 'draft' }) }),
    input({ shoppingToBuyCount: 3 }),
    input(),
  ]

  it('标题和描述都不为空, 可以带句号也可以不带', () => {
    for (const item of cases) {
      const step = nextStep(item)
      expect(step.title.trim().length).toBeGreaterThan(0)
      expect(step.description.trim().length).toBeGreaterThan(0)
    }
  })

  it('有按钮时一定有落点 (跳页或原地生成)', () => {
    for (const item of cases) {
      const step = nextStep(item)
      if (step.actionLabel) {
        expect(step.to !== null || step.isGenerateAction === true).toBe(true)
      }
    }
  })
})
