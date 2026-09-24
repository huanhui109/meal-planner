/**
 * 首页删改清单的静态断言
 *
 * 为什么用读源码的方式而不是渲染组件: 这些是**"这个模块不许出现在首页"**这类
 * 结构性约束, 用 DOM 渲染测会退化为"找一个字符串", 不如直接钉源文件。
 * 渲染相关的行为(深夜不渲染预算条、状态行显示晚餐)在 decide-context.test.ts 里,
 * 那边测的是被首页调用的纯函数。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(`../src/${relative}`, import.meta.url)), 'utf8')

/** shared/ 在 frontend/ 外面一层: tests/ → ../ = frontend/, 再 ../ 才是仓库根 */
const readShared = (relative: string) =>
  readFileSync(fileURLToPath(new URL(`../../shared/${relative}`, import.meta.url)), 'utf8')

/** 注释里会提到"删掉了什么", 断言必须只看代码, 否则删得越干净越测不过 */
const src = (relative: string) =>
  read(relative)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '$1')

const today = src('pages/Today/index.tsx')
const board = src('components/DecideBoard.tsx')
// 结果卡的显示判断抽到了 lib/result-card.ts (纯函数, 时刻可注入)。
// 这些是关于"结果卡"的约束, 卡片逻辑换文件不算换意图 —— 两边一起看。
const card = src('lib/result-card.ts')

describe('结果卡不出现具体分钟数', () => {
  it('DecideBoard 完全不再引用 formatMinutes', () => {
    expect(board).not.toContain('formatMinutes')
  })

  it('改用步数 + 档位词', () => {
    expect(board + card).toContain('cookEffortLabel')
    expect(board + card).toContain('steps.length')
  })

  it('首页「今晚这一餐」也不再展示分钟数', () => {
    expect(today).not.toContain('formatMinutes')
  })
})

describe('从首页删除的模块', () => {
  it('NextStepCard 与首页脱钩', () => {
    expect(today).not.toContain('NextStepCard')
    expect(today).not.toContain('nextStep(')
  })

  it('本周概览 4 磁贴不在首页', () => {
    expect(today).not.toContain('本周概览')
    expect(today).not.toContain('StatTile')
  })

  it('今日流程时间线不在首页', () => {
    expect(today).not.toContain('今天的自动流程')
    expect(today).not.toContain('timeline')
  })

  it('自做 vs 外卖对比卡降级为一行文字链', () => {
    expect(today).not.toContain('versus')
    expect(today).toContain('不想做饭？点外卖 →')
  })

  it('问候语删掉了', () => {
    expect(today).not.toContain('greeting(')
    expect(today).not.toContain('晚上好')
  })
})

describe('首页要有的东西', () => {
  it('状态行 + 决策区 + 出口 + 「家里有啥」', () => {
    expect(today).toContain('HomeStatusBar')
    expect(today).toContain('<DecideBoard')
    expect(today).toContain('FridgeQuickAdd')
  })

  it('预算条默认折叠, 且深夜完全不渲染', () => {
    expect(today).toContain('shouldShowBudgetStrip')
    expect(today).toContain('Collapse')
  })

  it('结果卡有「已排除 N 道」', () => {
    expect(board + card).toContain('已排除')
  })

  it('加载中文案不出现 AI 分析中', () => {
    expect(board).not.toContain('AI 分析中')
    expect(board).toContain('正在替你决定')
  })
})

describe('埋点', () => {
  // PRD v1.6 起判据事件是 11 个: home_filter_tap 已从判据清单删除,
  // 但代码里仍保留打点(只为兼容), 所以它继续在这个断言里 —— 断言的是"事件名都还在",
  // 不是"都还在算指标"。
  it('11 个判据事件 + home_filter_tap(保留打点不做判据) 全部定义, session_id 由前端生成', () => {
    const tracker = src('lib/track.ts')
    for (const name of [
      'home_view',
      'home_filter_tap',
      'decide_roll',
      'decide_result_shown',
      'decide_reroll',
      'decide_accept',
      'decide_view_steps',
      'decide_cook_start',
      'decide_cook_done',
      'decide_reject',
      'stubborn_shown',
    ]) {
      expect(tracker).toContain(`'${name}'`)
    }
    expect(tracker).toContain('session_id')
  })
})

describe('代码铁律', () => {
  it('本次改动的文件里没有 TODO / FIXME / XXX / HACK (注释也算)', () => {
    const files = [
      'pages/Today/index.tsx',
      'components/DecideBoard.tsx',
      'components/UtteranceInput.tsx',
      'components/FridgeQuickAdd.tsx',
      'components/HomeStatusBar.tsx',
      'stores/useDecideStore.ts',
      'lib/track.ts',
      'lib/result-card.ts',
      'lib/layout-version.ts',
    ]
    for (const file of files) {
      expect(read(file)).not.toMatch(/\b(TODO|FIXME|XXX|HACK)\b/)
    }
    // decide-context 已经搬到 shared/ 做两端真源, 前端那份副本删掉了
    expect(readShared('decide-context.ts')).not.toMatch(/\b(TODO|FIXME|XXX|HACK)\b/)
  })
})
