/**
 * 状态行与结果卡的渲染断言
 *
 * 为什么用 react-dom/server 而不是 @testing-library: 这个仓库的 vitest 跑在
 * node 环境(没装 jsdom), 而改首页要盯的是"某个时段下 DOM 里有没有某个东西",
 * 服务端渲染 + 假时钟足够, 不必为一个测试引入新依赖。
 *
 * ⚠ store 在这里是 mock 的: zustand v5 的 useSyncExternalStore 在服务端渲染时
 * 取的是**初始** state(getInitialState), 用 setState 灌不进去。所以这里 mock 掉
 * store、只断言组件 JSX 本身 —— 组件的真实取值逻辑在 decide-store.test.ts 里测。
 *
 * 钉死的三件事:
 *   1. 深夜结果卡不出现热量(说教类信息), 状态行显示「夜宵」
 *   2. 周六 17:00 状态行显示「晚餐」, 结果卡出现「再来一个」
 *   3. 结果卡任何时段都不出现具体分钟数
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import React from 'react'
import { renderToString } from 'react-dom/server'
import HomeStatusBar from '../src/components/HomeStatusBar'
import DecideBoard from '../src/components/DecideBoard'
import type { DecisionResult } from '../src/types'

const result: DecisionResult = {
  id: 9,
  dish: {
    recipe_id: 1,
    name: '番茄炒蛋',
    cuisine: '荤菜',
    category: '荤菜',
    cover_text: '',
    // 22 是"荤菜"的品类默认值, 正是不可信的那个数 —— 卡片上不许出现它
    cook_minutes: 22,
    calories: 320,
    difficulty: 1,
    main_ingredient: '鸡蛋',
    ingredients: ['鸡蛋', '番茄'],
    steps: ['番茄切块', '鸡蛋打散', '下锅炒', '出锅'],
  },
  reason: '冰箱的番茄快到期了',
  meal_slot: 'dinner',
  meal_slot_label: '晚餐',
  source: 'local',
  weather: {},
  advice: null,
  relaxed: false,
  decided_at: '2026-09-23T11:40:00',
}

const state = {
  result,
  loading: false,
  offline: false,
  round: 2,
  stubbornShown: false,
  error: '',
  slot: 'dinner' as const,
  excluded: ['宫保鸡丁', '红烧肉'],
  picked: [] as string[],
  utterance: '',
  intent: null,
  sessionId: 'session-for-test',
  resultShownAt: 0,
}

vi.mock('../src/stores/useDecideStore', () => ({
  useDecideStore: () => ({
    ...state,
    ensure: () => Promise.resolve(),
    roll: () => Promise.resolve(result),
    feedback: () => Promise.resolve(),
    setUtterance: () => undefined,
    accept: () => undefined,
    viewSteps: () => undefined,
    cookStart: () => undefined,
    cookDone: () => undefined,
    noteStubbornShown: () => undefined,
    reset: () => undefined,
  }),
  markCurrentExcluded: () => undefined,
  shouldShowStubborn: () => false,
  stubbornAfter: () => 3,
}))

vi.mock('../src/lib/track', () => ({
  track: () => undefined,
  flushNow: () => undefined,
  currentSessionId: () => 'session-for-test',
}))
vi.mock('../src/api/decide', () => ({
  decide: () => Promise.reject(new Error('offline')),
  getLastDecision: () => Promise.resolve(null),
  getDecideProfile: () => Promise.resolve(null),
  sendDecideFeedback: () => Promise.resolve({ accepted: true }),
  understandUtterance: () => Promise.resolve({ understood: false }),
}))

const board = () => renderToString(React.createElement(DecideBoard))
const statusOf = (fridgeCount: number | null) =>
  renderToString(React.createElement(HomeStatusBar, { fridgeCount }))

afterEach(() => vi.useRealTimers())

describe('深夜 23:40', () => {
  it('状态行显示夜宵, 结果卡不出现热量', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 23, 23, 40))
    expect(statusOf(6)).toContain('23:40 · 夜宵')
    expect(board()).not.toContain('kcal')
    vi.useRealTimers()
  })
})

describe('周六 17:00', () => {
  it('状态行显示晚餐', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 26, 17, 0))
    expect(statusOf(6)).toContain('17:00 · 晚餐 · 家里有 6 样')
    vi.useRealTimers()
  })

  it('结果卡出现「再来一个」(周末配菜, 不是换掉)', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 26, 17, 0))
    expect(board()).toContain('再来一个')
    vi.useRealTimers()
  })
})

describe('工作日 19:00', () => {
  it('不出现「再来一个」', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 21, 19, 0))
    expect(board()).not.toContain('再来一个')
    vi.useRealTimers()
  })
})

/**
 * 结果卡的断言一律只看**用户能看见的文字**, 不碰 class 名。
 *
 * 原因: class 名存在 ≠ 内容对 ≠ 字号对。写成 `toContain('decide-effort')` 是
 * 一条"跟着实现走的绿灯" —— 改个类名它就红, 而档位行真的被挪走了它照样绿。
 * 所以下面先把 SSR 出来的 HTML 剥成纯文本(顺带剥掉 React 插的 `<!-- -->`),
 * 再断言"用户读到的顺序"。字号那条归 `result-card.test.ts` 里读 CSS 的断言管,
 * 两条分工不重叠。
 */
const plainText = (html: string) => html.replace(/<[^>]*>/g, '')

describe('结果卡', () => {
  it('任何时段都不出现具体分钟数, 只有步数与档位', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 21, 19, 0))
    const html = board()
    const text = plainText(html)
    expect(text).not.toContain('分钟')
    expect(text).toMatch(/\d+\s*步/)
    // cook_minutes=22 落在"还行"档, 而不是把 22 这个品类默认值当成承诺
    expect(text).toContain('还行')
    expect(text).not.toContain('22')
    vi.useRealTimers()
  })

  it('把"系统在收敛"变成可见事实: 已排除 N 道', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 21, 19, 0))
    expect(plainText(board())).toContain('已排除 2 道')
    vi.useRealTimers()
  })

  /**
   * 契约级断言 (PRD G2): 步数 + 档位行必须同时出现, 且位置在**菜名之后、
   * 第一步做法之前** —— 它是第一眼信息, 不能被理由或广告挤到做法后面去。
   * 类名改了、CSS 变量改名了这条都不会红, 只有"档位行真的没了/被挪走了"才红。
   */
  it('步数与档位行同时出现, 且夹在菜名与第一步做法之间', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 21, 19, 0))
    const text = plainText(board())
    const nameAt = text.indexOf('番茄炒蛋')
    const firstStepAt = text.indexOf('番茄切块')
    expect(nameAt).toBeGreaterThanOrEqual(0)
    expect(firstStepAt).toBeGreaterThan(nameAt)

    const between = text.slice(nameAt, firstStepAt)
    expect(between, `菜名与做法之间的原文: ${between}`).toMatch(/\d+\s*步/)
    expect(between, `菜名与做法之间的原文: ${between}`).toMatch(/快手|还行|要小火慢炖/)
    vi.useRealTimers()
  })

  it('展示顺序: 菜名 → 理由 → 步数档位 → 做法', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 21, 19, 0))
    const text = plainText(board())
    let cursor = -1
    for (const token of ['番茄炒蛋', '冰箱的番茄快到期了', '步', '番茄切块']) {
      const at = text.indexOf(token, cursor + 1)
      expect(at, `「${token}」应出现在上一项之后`).toBeGreaterThan(cursor)
      cursor = at
    }
    vi.useRealTimers()
  })

  it('加载中文案不出现 AI 分析中', () => {
    expect(plainText(board())).not.toContain('AI 分析中')
  })
})
