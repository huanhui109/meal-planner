/**
 * 引导守卫的单测 —— 钉死"答完 3 题点进饭决必须回得去主页"
 *
 * 这组用例锁的是一条回归线: 首页守卫曾经只看配置 (shouldAutoShowGuide),
 * 不知道"本次启动已经弹过引导"。于是引导完成后回首页又被守卫推回引导页,
 * 用户永远进不去主页。现在守卫读的是 shouldAutoShowGuideNow。
 *
 * 两条必须同时成立的语义:
 *   1. 该弹的时候一定要弹 (不能因为加了闸门就再也不弹引导)
 *   2. 一次启动内只弹一次 (不能把用户锁在引导里)
 */
import { describe, expect, it, beforeEach } from 'vitest'
import {
  DEFAULT_USER_SETTINGS,
  hasAutoShownGuideThisLaunch,
  markGuideAutoShown,
  resetGuideAutoShowForTest,
  shouldAutoShowGuide,
  shouldAutoShowGuideNow,
  type UserSettings,
} from '../shared/user-settings'

function settings(patch: Partial<UserSettings['guide']>): UserSettings {
  return { ...DEFAULT_USER_SETTINGS, guide: { ...DEFAULT_USER_SETTINGS.guide, ...patch } }
}

beforeEach(() => {
  // 模拟冷启动: 闸门在模块级, 每个用例都要从"没弹过"开始
  resetGuideAutoShowForTest()
})

describe('shouldAutoShowGuide (纯规则, 只看配置)', () => {
  it('once + 未完成 → 展示', () => {
    expect(shouldAutoShowGuide(settings({ showMode: 'once', completed: false }))).toBe(true)
  })

  it('once + 已完成 → 不展示', () => {
    expect(shouldAutoShowGuide(settings({ showMode: 'once', completed: true }))).toBe(false)
  })

  it('always → 永远展示 (所以才必须有启动闸门, 否则回主页必被推回引导)', () => {
    expect(shouldAutoShowGuide(settings({ showMode: 'always', completed: true }))).toBe(true)
  })

  it('never → 永远不展示', () => {
    expect(shouldAutoShowGuide(settings({ showMode: 'never', completed: false }))).toBe(false)
  })

  it('总开关关掉 → 不展示', () => {
    expect(shouldAutoShowGuide(settings({ enabled: false, showMode: 'always' }))).toBe(false)
  })
})

describe('shouldAutoShowGuideNow (一次启动只弹一次的闸门)', () => {
  it('新用户首次进首页 → 弹', () => {
    expect(shouldAutoShowGuideNow(settings({ completed: false }))).toBe(true)
  })

  /**
   * 关键: H5 开了 StrictMode, 渲染期会被 React 双调用。
   * 判断必须是纯读 —— 连调 3 次结果要一致, 否则第二次渲染返回 false,
   * 重定向永远不触发, 引导就彻底不弹了 (比回弹更隐蔽)。
   */
  it('连调多次结果一致 (StrictMode 双渲染安全)', () => {
    const s = settings({ completed: false })
    expect(shouldAutoShowGuideNow(s)).toBe(true)
    expect(shouldAutoShowGuideNow(s)).toBe(true)
    expect(shouldAutoShowGuideNow(s)).toBe(true)
    expect(hasAutoShownGuideThisLaunch()).toBe(false)
  })

  it('弹过之后本次启动不再弹 —— 这是「进饭决」能回主页的原因', () => {
    const s = settings({ showMode: 'always', completed: true })
    expect(shouldAutoShowGuideNow(s)).toBe(true)
    markGuideAutoShown()
    expect(hasAutoShownGuideThisLaunch()).toBe(true)
    expect(shouldAutoShowGuideNow(s)).toBe(false)
  })

  /**
   * 完整流程回归: 冷启动 → 守卫弹引导 → 引导答完回首页 → 守卫不再拦。
   * showMode=每次启动 是这条路径最容易被打穿的配置。
   */
  it('always 模式下走完一遍引导也能回到主页', () => {
    const s = settings({ showMode: 'always', completed: false })
    // 1. 冷启动进首页, 守卫判定该弹
    expect(shouldAutoShowGuideNow(s)).toBe(true)
    markGuideAutoShown()
    // 2. 引导里答完 3 题 (markGuideCompleted 让 completed=true; 这里直接构造)
    const after = settings({ showMode: 'always', completed: true })
    // 3. 点「进饭决」回首页 —— 守卫必须放行
    expect(shouldAutoShowGuideNow(after)).toBe(false)
  })

  it('once + 已完成 → 即使没弹过也不展示', () => {
    expect(shouldAutoShowGuideNow(settings({ completed: true }))).toBe(false)
  })

  it('resetGuideAutoShowForTest 能重置闸门 (模拟下次冷启动)', () => {
    markGuideAutoShown()
    expect(hasAutoShownGuideThisLaunch()).toBe(true)
    resetGuideAutoShowForTest()
    expect(hasAutoShownGuideThisLaunch()).toBe(false)
    // 冷启动后 always 模式会再弹一次 —— 这是用户主动选的语义, 不算回归
    expect(shouldAutoShowGuideNow(settings({ showMode: 'always', completed: true }))).toBe(true)
  })
})
