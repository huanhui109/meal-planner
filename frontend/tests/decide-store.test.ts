/**
 * 「换一个」必须同时上报 reject —— 现状前端从不调 feedback(false),
 * 于是 decision_log.accepted 有 85.3% 是 NULL, "采纳率"这个指标等于不存在。
 *
 * 这个文件钉死两件事:
 *   1. 点「换一个」时 decide_reject + decide_reroll 都要打
 *   2. 同时要真的 POST /decide/{id}/feedback { liked: false }
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sendDecideFeedback } from '../src/api/decide'
import { track } from '../src/lib/track'
import { markCurrentExcluded, useDecideStore } from '../src/stores/useDecideStore'
import type { DecisionResult } from '../src/types'

vi.mock('../src/lib/track', () => ({
  track: vi.fn(),
  flushNow: vi.fn(),
  currentSessionId: () => 'session-for-test',
}))

vi.mock('../src/api/decide', () => ({
  decide: vi.fn(),
  getLastDecision: vi.fn(),
  getDecideProfile: vi.fn(),
  sendDecideFeedback: vi.fn(),
  understandUtterance: vi.fn(),
}))

const dish = (name: string) => ({
  recipe_id: 1,
  name,
  cuisine: '荤菜',
  category: '荤菜',
  cover_text: '',
  cook_minutes: 22,
  calories: 320,
  difficulty: 2,
  main_ingredient: '鸡蛋',
  ingredients: ['鸡蛋'],
  steps: ['打蛋', '下锅', '出锅'],
})

const result = (name: string, id = 11): DecisionResult => ({
  id,
  dish: dish(name),
  reason: '冰箱的鸡蛋快到期了',
  meal_slot: 'dinner',
  meal_slot_label: '晚餐',
  source: 'local',
  weather: {},
  advice: null,
  relaxed: false,
  decided_at: new Date().toISOString(),
})

const next = result('冬瓜汤', 12)

describe('换一个 = 换掉 + 上报 reject', () => {
  beforeEach(() => {
    vi.mocked(track).mockClear()
    vi.mocked(sendDecideFeedback).mockClear()
    vi.mocked(sendDecideFeedback).mockResolvedValue({ accepted: false })
    useDecideStore.setState({
      result: result('番茄炒蛋'),
      excluded: [],
      picked: [],
      round: 1,
      stubbornShown: false,
      utterance: '',
      loading: false,
      resultShownAt: Date.now() - 3000,
    })
  })

  it('打点里同时有 decide_reject 和 decide_reroll', async () => {
    const { decide } = await import('../src/api/decide')
    vi.mocked(decide).mockResolvedValueOnce(next as never)

    await useDecideStore.getState().roll({ intent: 'reroll' })

    const events = vi.mocked(track).mock.calls.map((call) => call[0])
    expect(events).toContain('decide_reject')
    expect(events).toContain('decide_reroll')
    expect(events).toContain('decide_result_shown')
  })

  it('真的调了 feedback(false) —— 否则 accepted 永远是 NULL', async () => {
    const { decide } = await import('../src/api/decide')
    vi.mocked(decide).mockResolvedValueOnce(next as never)

    await useDecideStore.getState().roll({ intent: 'reroll' })

    expect(sendDecideFeedback).toHaveBeenCalledWith(11, false)
  })

  it('换掉的菜进 exclude, 不会再来一次', async () => {
    const { decide } = await import('../src/api/decide')
    vi.mocked(decide).mockResolvedValueOnce(next as never)

    markCurrentExcluded('reroll')
    expect(useDecideStore.getState().excluded).toEqual(['番茄炒蛋'])

    await useDecideStore.getState().roll({ intent: 'reroll' })
    expect(useDecideStore.getState().excluded).toEqual(['番茄炒蛋'])
  })

  it('周末「再来一个」: 菜只进 picked(今晚已定), 不进 excluded', async () => {
    const { decide } = await import('../src/api/decide')
    vi.mocked(decide).mockResolvedValueOnce(next as never)

    markCurrentExcluded('another_dish')
    const state = useDecideStore.getState()
    expect(state.picked).toEqual(['番茄炒蛋'])
    // 她不是在换掉这道菜, 是在配一桌菜 —— 记进"已排除"等于把定下的说成淘汰的
    expect(state.excluded).toEqual([])

    await useDecideStore.getState().roll({ intent: 'another_dish' })
    const rerollCall = vi
      .mocked(track)
      .mock.calls.find((call) => call[0] === 'decide_reroll')
    expect(rerollCall?.[1]).toMatchObject({ reroll_intent: 'another_dish' })
  })

  it('已定下的菜不会再来一遍 —— 请求时 picked 一起当 exclude 传', async () => {
    const { decide } = await import('../src/api/decide')
    vi.mocked(decide).mockClear()
    vi.mocked(decide).mockResolvedValueOnce(next as never)
    useDecideStore.setState({ excluded: ['冬瓜汤'], picked: ['番茄炒蛋'] })

    await useDecideStore.getState().roll({ intent: 'another_dish' })

    const payload = vi.mocked(decide).mock.calls[0][0] as { exclude: string[] }
    expect(payload.exclude).toEqual(expect.arrayContaining(['番茄炒蛋', '冬瓜汤']))
  })
})

describe('就这个 = 采纳 + 记录犹豫时长', () => {
  it('decide_accept 带 result_age_ms, 并调 feedback(true)', async () => {
    vi.mocked(track).mockClear()
    vi.mocked(sendDecideFeedback).mockClear()
    vi.mocked(sendDecideFeedback).mockResolvedValue({ accepted: true })
    useDecideStore.setState({ result: result('番茄炒蛋'), resultShownAt: Date.now() - 4200 })

    useDecideStore.getState().accept()

    const call = vi.mocked(track).mock.calls.find((c) => c[0] === 'decide_accept')
    expect(call).toBeTruthy()
    expect(call?.[1]).toMatchObject({ dish: '番茄炒蛋' })
    expect((call?.[1] as { result_age_ms: number }).result_age_ms).toBeGreaterThanOrEqual(4000)
    expect(sendDecideFeedback).toHaveBeenCalledWith(11, true)
  })
})

describe('服务端返回空也要有答案', () => {
  it('data 为 null 时落本地池并打离线角标 —— 不靠 TypeError 兜', async () => {
    const { decide } = await import('../src/api/decide')
    vi.mocked(decide).mockResolvedValueOnce(null as never)
    useDecideStore.setState({ result: null, excluded: [], picked: [], round: 0, offline: false })

    const out = await useDecideStore.getState().roll({ intent: 'fresh' })

    // 断言的是"永远有答案"这条承诺, 不是"当前实现恰好能跑":
    // 以前它是 result.dish.name 抛 TypeError 的副产品, 加个 ?. 就会静默退化成空态
    expect(out).not.toBeNull()
    expect(useDecideStore.getState().offline).toBe(true)
    expect(useDecideStore.getState().error).toBe('')
  })
})

describe(' utterance 永远可空', () => {
  it('没说话时请求体里 utterance 是空串, 行为与现状一致', async () => {
    const { decide } = await import('../src/api/decide')
    vi.mocked(decide).mockClear()
    vi.mocked(decide).mockResolvedValueOnce(next as never)
    useDecideStore.setState({ result: null, excluded: [], utterance: '', round: 0 })

    await useDecideStore.getState().roll({ intent: 'fresh' })

    expect(vi.mocked(decide).mock.calls[0][0]).toMatchObject({ utterance: '' })
  })
})
