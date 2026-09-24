/**
 * layout_version 必须进每一个埋点 (R-16)
 *
 * 为什么不能用 app 版本号: 同一个 app 版本的用户可能落在 v1.1 / v1.2 两个灰度组,
 * 只有服务端下发的值能把"改版是好是坏"切开。事件里少这个字段, 这条数据在灰度分析
 * 里就永远是废的 —— 而且这种缺失事后补不回来(事件已经落库了)。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reportEvents } from '../src/api/events'
import { flushNow, track, __resetForTest } from '../src/lib/track'
import {
  applyServerLayoutVersion,
  getLayoutVersion,
  resetLayoutVersionForTest,
} from '../src/lib/layout-version'

vi.mock('../src/api/events', () => ({
  reportEvents: vi.fn(() => Promise.resolve({ ok: true })),
}))

/** 攒批是 1.2 秒后发, 这里直接 flushNow() 把队列拍出来看 */
function flushed(): Array<{
  event_name: string
  properties: Record<string, unknown>
  session_id: string | null
  decision_id: number | null
  app_version: string | null
  layout_version: string | null
}> {
  flushNow()
  const calls = vi.mocked(reportEvents).mock.calls
  return calls.flatMap((call) => call[0] as never[])
}

describe('layout_version 进全部埋点', () => {
  beforeEach(() => {
    __resetForTest()
    vi.mocked(reportEvents).mockClear()
  })

  afterEach(() => {
    resetLayoutVersionForTest()
  })

  it('每个事件都自动带上 layout_version, 调用方不用记着传', () => {
    track('decide_roll', { reroll_index: 1 })
    track('decide_accept', { dish: '番茄炒蛋' })

    const batch = flushed()
    expect(batch.map((e) => e.event_name)).toEqual(['decide_roll', 'decide_accept'])
    for (const event of batch) {
      // session_id / layout_version 都走请求体顶层(后端各有独立列, layout_version 有
      // 迁移 0019 的独立列), properties 里不再重复写 —— 重复写会让后端那两条回落
      // 分支永远删不掉。后端现在对两个字段都有 properties 回落, 所以旧行为不会丢数据,
      // 但契约以顶层为准。
      expect(event.layout_version).toBe('v1.2')
      expect(event.session_id).toEqual(expect.any(String))
      expect(event.properties).not.toHaveProperty('session_id')
      expect(event.properties).not.toHaveProperty('layout_version')
      // R-16a: 真实版本号, 不能是 unknown
      expect(event.app_version).toBeTruthy()
      expect(event.app_version).not.toBe('unknown')
    }
  })

  it('服务端下发 v1.1 后, 之后的事件跟着切', () => {
    applyServerLayoutVersion('v1.1')
    track('home_view', { meal_slot: 'dinner' })

    expect(flushed()[0].layout_version).toBe('v1.1')
    expect(getLayoutVersion()).toBe('v1.1')
  })

  it('服务端下发空值/脏值时保持原值 —— 不拿 null 污染灰度切片', () => {
    const before = getLayoutVersion()
    applyServerLayoutVersion(null)
    applyServerLayoutVersion('')
    applyServerLayoutVersion(undefined)
    applyServerLayoutVersion(42)
    expect(getLayoutVersion()).toBe(before)
  })
})
