/**
 * session_id 必须贯穿 (R-06)
 *
 * 这是 J1 闭环率唯一的分母来源: 一次"打开首页 → 定下来"里的所有事件共用同一个值。
 * 断掉的方式有三种, 每一种都不报错 —— 所以必须钉死:
 *   1. 每个事件现生成一个 uuid (会话数 = 事件数, 闭环率恒等于 1/事件数)
 *   2. localStorage 不可用时退化成 1 (隐私模式 / 配额满的机器上静默失效)
 *   3. 把 session_id 塞进 properties 而不是顶层列 (后端有独立列 + 索引, 走列才查得动)
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reportEvents } from '../src/api/events'
import { currentSessionId, flushNow, track, __resetForTest } from '../src/lib/track'

vi.mock('../src/api/events', () => ({
  reportEvents: vi.fn(() => Promise.resolve({ accepted: 0, skipped: 0 })),
}))

type Sent = {
  event_name: string
  session_id: string | null
  decision_id: number | null
  app_version: string | null
  properties: Record<string, unknown>
}

const flushed = (): Sent[] => {
  flushNow()
  return vi.mocked(reportEvents).mock.calls.flatMap((call) => call[0] as never[])
}

describe('session_id 贯穿', () => {
  beforeEach(() => {
    __resetForTest()
    vi.mocked(reportEvents).mockClear()
  })

  it('一批事件共用一个 session_id', () => {
    track('home_view', { meal_slot: 'dinner' })
    track('decide_roll', { reroll_index: 0 })
    track('decide_result_shown', { decision_id: 4321, dish: '番茄炒蛋' })
    track('decide_accept', { decision_id: 4321, dish: '番茄炒蛋' })

    const batch = flushed()
    const ids = new Set(batch.map((e) => e.session_id))
    expect(ids.size).toBe(1)
    // 测试环境没有 localStorage, 这条同时证明"存储不可用时页内仍然恒定"
    expect(batch[0].session_id).toBe(currentSessionId())
  })

  it('放在请求体顶层, properties 里不再重复写', () => {
    track('decide_roll', { reroll_index: 1 })
    const [event] = flushed()
    expect(event.session_id).toEqual(expect.any(String))
    expect(event.properties).not.toHaveProperty('session_id')
  })

  it('decision_id 从 props 提到顶层; 没有就留 null', () => {
    track('home_view', { meal_slot: 'dinner' })
    track('decide_result_shown', { decision_id: 4321 })
    const batch = flushed()
    expect(batch[0].decision_id).toBeNull()
    expect(batch[1].decision_id).toBe(4321)
    expect(batch[1].properties).not.toHaveProperty('decision_id')
  })

  it('app_version 是真实版本号 (R-16a)', () => {
    track('home_view', {})
    expect(flushed()[0].app_version).toMatch(/^\d+\.\d+\.\d+$/)
  })
})
