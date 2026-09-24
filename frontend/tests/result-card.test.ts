/**
 * 结果卡三个验收时刻 —— 19:20 工作日 / 23:40 周三深夜 / 周六 17:00
 *
 * 时刻全部靠 buildResultCard 的 now 参数注入, 不用 vi.useFakeTimers():
 * 假定时器会把 zustand 的攒批定时器一起假掉, 一个用例污染一整个文件。
 *
 * 这组断言钉的是"同一张卡在三种人手里是三种东西":
 *   上班族 19:20 = 快点定下来(有热量、没有配菜入口)
 *   深夜 23:40  = 别跟我说教(热量完全不渲染)
 *   周六 17:00  = 我在配一桌菜(多一个「再来一个」)
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { buildResultCard, RELAXED_TEXT } from '../src/lib/result-card'
import { stubbornAfter } from '@shared/decide-context'
import { shouldShowStubborn } from '../src/stores/useDecideStore'
import type { DecisionResult } from '../src/types'

/** 2026-09-23 是周三, 09-26 是周六 —— 星期从日期来, 不靠 mock */
const WED_1920 = new Date(2026, 8, 23, 19, 20)
const WED_2340 = new Date(2026, 8, 23, 23, 40)
const SAT_1700 = new Date(2026, 8, 26, 17, 0)

const result = (patch: Partial<DecisionResult> = {}): DecisionResult => ({
  id: 11,
  dish: {
    recipe_id: 1,
    name: '番茄炒蛋',
    cuisine: '家常',
    category: '荤菜',
    cover_text: '',
    cook_minutes: 22,
    calories: 320,
    difficulty: 2,
    main_ingredient: '鸡蛋',
    ingredients: ['鸡蛋', '番茄'],
    steps: ['打蛋', '热锅', '下蛋', '下番茄', '出锅'],
  },
  reason: '冰箱的鸡蛋快到期了',
  meal_slot: 'dinner',
  meal_slot_label: '晚餐',
  source: 'local',
  weather: {},
  advice: null,
  relaxed: false,
  decided_at: new Date(2026, 8, 23, 19, 20).toISOString(),
  ...patch,
})

describe('周三 19:20 · 工作日晚餐', () => {
  it('档位是档位词不是分钟数, 热量照常给', () => {
    const card = buildResultCard({ result: result(), now: WED_1920, excludedCount: 0, pickedCount: 0 })
    expect(card.bucket).toBe('weekday')
    expect(card.effortLabel).toBe('还行') // 22 分钟落在 15-30 档
    expect(card.stepCount).toBe(5)
    expect(card.showKcal).toBe(true)
    expect(card.footnote).toBeNull()
    expect(card.showAnotherDish).toBe(false)
  })

  it('倔强阈值是 3 次', () => {
    expect(stubbornAfter(WED_1920)).toBe(3)
    expect(shouldShowStubborn(2, false, WED_1920)).toBe(false)
    expect(shouldShowStubborn(3, false, WED_1920)).toBe(true)
  })

  it('换过一次就写「已排除 1 道」', () => {
    const card = buildResultCard({ result: result(), now: WED_1920, excludedCount: 1, pickedCount: 0 })
    expect(card.footnote).toBe('excluded')
    expect(card.footnoteText).toBe('已排除 1 道')
  })
})

describe('周三 23:40 · 深夜', () => {
  it('热量完全不渲染 —— 深夜给用户看营养不是提醒是添堵', () => {
    const card = buildResultCard({ result: result(), now: WED_2340, excludedCount: 2, pickedCount: 0 })
    expect(card.bucket).toBe('late_night')
    expect(card.showKcal).toBe(false)
    expect(card.kcalText).toBeNull()
  })

  it('倔强阈值收紧到 2 次 —— 深夜的耐心只有几秒', () => {
    expect(stubbornAfter(WED_2340)).toBe(2)
    expect(shouldShowStubborn(2, false, WED_2340)).toBe(true)
  })

  it('深夜没有「再来一个」', () => {
    const card = buildResultCard({ result: result(), now: WED_2340, excludedCount: 0, pickedCount: 0 })
    expect(card.showAnotherDish).toBe(false)
  })
})

describe('周六 17:00 · 周末配菜', () => {
  it('出现「再来一个」, 倔强阈值放宽到 5 次', () => {
    const card = buildResultCard({ result: result(), now: SAT_1700, excludedCount: 0, pickedCount: 0 })
    expect(card.bucket).toBe('weekend')
    expect(card.showAnotherDish).toBe(true)
    expect(stubbornAfter(SAT_1700)).toBe(5)
    // 周末的人是在配一桌菜, 第 3 次就锁住她是负体验
    expect(shouldShowStubborn(3, false, SAT_1700)).toBe(false)
  })

  it('已定的菜写成「今晚已定 N 道」, 不算负面信息', () => {
    const card = buildResultCard({ result: result(), now: SAT_1700, excludedCount: 0, pickedCount: 2 })
    expect(card.pickedText).toBe('今晚已定 2 道')
    expect(card.footnote).toBeNull()
  })
})

describe('一次只能有一个负面信息', () => {
  it('放宽优先于去重 —— 两条不叠在一起', () => {
    const card = buildResultCard({
      result: result({ relaxed: true, advice: '可选项不多，放宽了一点条件' }),
      now: WED_1920,
      excludedCount: 5,
      pickedCount: 0,
    })
    expect(card.footnote).toBe('relaxed')
    expect(card.footnoteText).toBe(RELAXED_TEXT)
    // 后端 relaxed 时 advice 说的是同一件事, 标注已经替它说了, 不再重复一遍
    expect(card.showAdvice).toBe(false)
  })

  it('没放宽时 advice 照常给', () => {
    const card = buildResultCard({
      result: result({ advice: '这种天出门不值当，交给外卖吧' }),
      now: WED_1920,
      excludedCount: 0,
      pickedCount: 0,
    })
    expect(card.showAdvice).toBe(true)
  })
})

describe('结果卡上不出现分钟数字', () => {
  it('档位只给词, 整个视图模型里没有 N 分钟', () => {
    const card = buildResultCard({
      result: result({ dish: { ...result().dish, cook_minutes: 22 } }),
      now: WED_1920,
      excludedCount: 3,
      pickedCount: 1,
    })
    expect(card.effortLabel).not.toMatch(/\d/)
    expect(JSON.stringify(card)).not.toMatch(/分钟/)
  })
})

/**
 * PRD G2 的度量: 「步数 + 档位词」是"定了就信"的三个支点之一,
 * 字号必须 ≥ 菜名字号的 0.8 倍。这条是纯 CSS 数字, 没人会在真机上量,
 * 只能静态钉住 —— 否则改样式的人顺手调小一档, 支点就悄悄降级成脚注了。
 */
describe('步数 + 档位行的字号', () => {
  const css = readFileSync(
    fileURLToPath(new URL('../src/global.css', import.meta.url)),
    'utf8',
  )
  const tokens = readFileSync(
    fileURLToPath(new URL('../src/styles/tokens.css', import.meta.url)),
    'utf8',
  )

  /** 把 var(--font-xxx) 解析成 px; 认不出来就返回 null, 让断言明确失败 */
  const px = (value: string): number | null => {
    const direct = value.match(/(\d+(?:\.\d+)?)px/)
    if (direct) return Number(direct[1])
    const token = value.match(/var\(--([\w-]+)\)/)
    if (!token) return null
    const defined = tokens.match(new RegExp(`--${token[1]}:\\s*(\\d+(?:\\.\\d+)?)px`))
    return defined ? Number(defined[1]) : null
  }

  const fontSizeOf = (selector: string): number | null => {
    const block = css.match(new RegExp(`^\\${selector}\\s*\\{([^}]*)\\}`, 'm'))
    if (!block) return null
    const size = block[1].match(/font-size:\s*([^;]+);/)
    return size ? px(size[1]) : null
  }

  it('档位行字号 ≥ 菜名字号的 0.8 倍', () => {
    const dishName = fontSizeOf('.decide-dish-name')
    const effort = fontSizeOf('.decide-effort')
    expect(dishName).toBeGreaterThan(0)
    expect(effort).toBeGreaterThan(0)
    expect(effort!).toBeGreaterThanOrEqual(dishName! * 0.8)
  })
})
