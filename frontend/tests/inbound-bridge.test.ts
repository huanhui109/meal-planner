/**
 * T05：双向唤醒模块前端契约回归（Vitest，零新增依赖）。
 *
 * 重点是把 shared/ 的枚举/文案、inboundBridgeSign.ts 的 stableStringify + 两步 HMAC，
 * 与 Python 后端算出的**同一份固定向量**双向钉住。向量由后端
 * `TokenService.canonical` + `derive_key` 重新计算（见
 * backend/tests/unit/test_inbound_tokens.py 顶部说明），没有硬抄 T04 的
 * data_hash / sig —— 那对应另一份 envelope，字段不同 sig 必然不同。
 *
 * 签名测试同时用两种方式验证：node:crypto 独立复算（不依赖 WebCrypto），
 * 以及调用真实的 signEnvelope()（用 node:crypto 的 webcrypto 桩保证 crypto.subtle 可用）。
 */
import { createHash, createHmac, webcrypto } from 'node:crypto'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ALLOWED_EVENTS,
  FROZEN_FORBIDDEN,
  INBOUND_ACTIVE_STATUSES,
  INBOUND_ALLOWLIST_VERSION,
  INBOUND_DIRECTIONS,
  INBOUND_EVENT_TYPES,
  INBOUND_PHASES,
  INBOUND_PROTOCOL_VERSION,
  INBOUND_TASK_STATUSES,
  inboundBridgeLabel,
  inboundBridgePending,
} from '@shared/inboundBridge'
import { ENDPOINTS } from '@shared/endpoints'
import {
  canonical,
  signEnvelope,
  stableStringify,
  type InboundEnvelope,
} from '../src/lib/inboundBridgeSign'

// ---------------------------------------------------------------- 跨语言固定向量
const PLAINTEXT = 'fd_ib_web_TEST_VECTOR_TOKEN_0123456789abcdef'
const FIXED_DATA = {
  context: {
    avoid: ['香菜', '花生'],
    meal_date: '2026-11-05',
    meal_slot: 'dinner',
    mode: 'takeout',
    servings: 2,
    max_minutes: 30,
    budget: null,
    max_spice: 2,
    vegetarian: false,
    light: false,
    use_fridge: true,
    avoid_recent: true,
  },
  expected_revision: 7,
  instruction: '今晚两个人，不想开火，清淡一点「别太辣」',
  request_id: '11111111-2222-3333-4444-555555555555',
}
const FIXED_STABLE =
  '{"context":{"avoid":["香菜","花生"],"avoid_recent":true,"budget":null,' +
  '"light":false,"max_minutes":30,"max_spice":2,"meal_date":"2026-11-05",' +
  '"meal_slot":"dinner","mode":"takeout","servings":2,"use_fridge":true,' +
  '"vegetarian":false},"expected_revision":7,' +
  '"instruction":"今晚两个人，不想开火，清淡一点「别太辣」",' +
  '"request_id":"11111111-2222-3333-4444-555555555555"}'
const FIXED_DATA_HASH = 'b803bab3a1ecd362b30a52fd4cd7bf26593d89a67924bc754e2e2934d11e379a'
const FIXED_CANONICAL = [
  '1',
  'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
  'web_to_bridge',
  'meal.adjust.requested',
  '', // task_id 为空
  '-',
  '11111111-2222-4333-8444-555555555555',
  '66666666-7777-4888-8999-000000000000',
  'abcdefab-1234-4567-8abc-1234567890ab',
  '1762329600',
  'fandecide-t05-regression-nonce',
  'ib-1.0',
  FIXED_DATA_HASH,
].join('\n')
const FIXED_SIG = '864b2c9726de429e392f4678c44df3fff9030d1d25a47588d5532973c1d156b0'

const ENVELOPE: InboundEnvelope = {
  v: 1,
  pair_id: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
  direction: 'web_to_bridge',
  event_type: 'meal.adjust.requested',
  task_id: '',
  phase: '-',
  assistant_instance_id: '11111111-2222-4333-8444-555555555555',
  session_id: '66666666-7777-4888-8999-000000000000',
  event_id: 'abcdefab-1234-4567-8abc-1234567890ab',
  issued_at: 1762329600,
  nonce: 'fandecide-t05-regression-nonce',
  allowlist_version: INBOUND_ALLOWLIST_VERSION,
  data: FIXED_DATA,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('shared 枚举与版本（服务端独立硬编码同值）', () => {
  it('版本 ib-1.0 / 协议 v=1', () => {
    expect(INBOUND_ALLOWLIST_VERSION).toBe('ib-1.0')
    expect(INBOUND_PROTOCOL_VERSION).toBe(1)
  })

  it('INBOUND_EVENT_TYPES 九类、ALLOWED_EVENTS 六 enabled 三 disabled', () => {
    expect(INBOUND_EVENT_TYPES).toHaveLength(9)
    const keys = Object.keys(ALLOWED_EVENTS)
    expect(keys).toHaveLength(9)
    expect(new Set(keys)).toEqual(new Set(INBOUND_EVENT_TYPES))
    expect(keys.filter((k) => ALLOWED_EVENTS[k as keyof typeof ALLOWED_EVENTS].enabled)).toHaveLength(6)
    expect(keys.filter((k) => !ALLOWED_EVENTS[k as keyof typeof ALLOWED_EVENTS].enabled)).toHaveLength(3)
  })

  it('FROZEN_FORBIDDEN 16 条，含两个通配符', () => {
    expect(FROZEN_FORBIDDEN).toHaveLength(16)
    expect(FROZEN_FORBIDDEN).toContain('order.*')
    expect(FROZEN_FORBIDDEN).toContain('payment.*')
    expect(FROZEN_FORBIDDEN).toContain('meal.accept')
    expect(FROZEN_FORBIDDEN).toContain('event.unlisted')
  })

  it('方向 / 阶段 / 状态 / 在途状态枚举完整', () => {
    expect(INBOUND_DIRECTIONS).toEqual(['web_to_bridge', 'assistant_to_bridge', 'bridge_to_assistant'])
    expect(INBOUND_PHASES).toEqual(['-', 'context', 'proposal'])
    expect(INBOUND_TASK_STATUSES).toHaveLength(15)
    expect(INBOUND_ACTIVE_STATUSES).toHaveLength(6)
    expect(new Set(INBOUND_ACTIVE_STATUSES).size).toBe(6)
  })
})

describe('inboundBridgeLabel 逐档文案', () => {
  it('每个状态都有独立文案，异常态如实说明原方案未改变', () => {
    for (const status of INBOUND_TASK_STATUSES) {
      const label = inboundBridgeLabel(status)
      expect(label.length).toBeGreaterThan(0)
      expect(label).not.toBe('状态未知，请刷新后查询')
    }
    expect(inboundBridgeLabel('awaiting_assistant')).toContain('原方案未改变')
    expect(inboundBridgeLabel('validating')).toContain('原方案未改变')
    expect(inboundBridgeLabel('proposed')).toBe('新方案已保存，等你决定')
    expect(inboundBridgeLabel('offline')).toContain('离线')
    expect(inboundBridgeLabel('awaiting_user_approval')).toContain('请在 WorkBuddy 中查看')
    expect(inboundBridgeLabel('uncertain')).toContain('不会自动重复发送')
  })

  it('未知状态走兜底文案', () => {
    expect(inboundBridgeLabel('not-a-status')).toBe('状态未知，请刷新后查询')
  })
})

describe('inboundBridgePending 在途判定', () => {
  it('只有 6 个在途状态判定为在途，终止态一律 false', () => {
    for (const status of INBOUND_ACTIVE_STATUSES) {
      expect(inboundBridgePending(status)).toBe(true)
    }
    const terminal = INBOUND_TASK_STATUSES.filter(
      (s) => !(INBOUND_ACTIVE_STATUSES as readonly string[]).includes(s),
    )
    expect(terminal.length).toBe(9)
    for (const status of terminal) {
      expect(inboundBridgePending(status)).toBe(false)
    }
    expect(inboundBridgePending('garbage')).toBe(false)
  })
})

describe('stableStringify 与 Python json.dumps 固定向量一致', () => {
  it('中文不转义、键排序、无空白，且 sha256 == 后端 data_hash', () => {
    const stable = stableStringify(FIXED_DATA)
    expect(stable).toBe(FIXED_STABLE)
    expect(stable).toContain('香菜')
    expect(stable).not.toContain('\\u')
    expect(stable).not.toContain(', ')
    expect(stable).not.toContain(': ')
    expect(stable).not.toContain('\n')
    expect(stable.indexOf('"avoid_recent"')).toBeLessThan(stable.indexOf('"budget"'))
    expect(createHash('sha256').update(Buffer.from(stable, 'utf8')).digest('hex')).toBe(FIXED_DATA_HASH)
  })

  it('对象键递归排序，并拒绝 NaN / Infinity / undefined（对齐 allow_nan=False）', () => {
    expect(stableStringify({ b: 1, a: 2 })).toBe('{"a":2,"b":1}')
    expect(stableStringify({ z: { b: 1, a: [true, null, '中文'] } })).toBe(
      '{"z":{"a":[true,null,"中文"],"b":1}}',
    )
    expect(() => stableStringify({ x: NaN })).toThrow()
    expect(() => stableStringify({ x: Infinity })).toThrow()
    expect(() => stableStringify(undefined)).toThrow()
  })

  it('canonical 13 行与后端 TokenService.canonical 逐字一致', () => {
    expect(canonical(ENVELOPE, FIXED_DATA_HASH)).toBe(FIXED_CANONICAL)
    expect(FIXED_CANONICAL.split('\n')).toHaveLength(13)
  })
})

describe('两步 HMAC sig 与 Python 后端固定向量一致', () => {
  it('node:crypto 独立复算命中固定 sig，且错令牌产生不同 sig', () => {
    const signingKey = createHmac('sha256', Buffer.from(PLAINTEXT, 'utf8'))
      .update(Buffer.from('fandecide.inbound.sign.v1', 'utf8'))
      .digest()
    expect(signingKey).toHaveLength(32)
    const sig = createHmac('sha256', signingKey)
      .update(Buffer.from(FIXED_CANONICAL, 'utf8'))
      .digest('hex')
    expect(sig).toBe(FIXED_SIG)
    const wrongKey = createHmac('sha256', Buffer.from(PLAINTEXT + 'x', 'utf8'))
      .update(Buffer.from('fandecide.inbound.sign.v1', 'utf8'))
      .digest()
    const wrongSig = createHmac('sha256', wrongKey)
      .update(Buffer.from(FIXED_CANONICAL, 'utf8'))
      .digest('hex')
    expect(wrongSig).not.toBe(FIXED_SIG)
  })

  it('真实 signEnvelope() 也命中同一个固定 sig', async () => {
    // 用 node:crypto 的 webcrypto 桩保证 Vitest(node) 下 crypto.subtle 一定可用。
    vi.stubGlobal('crypto', webcrypto)
    expect(await signEnvelope(ENVELOPE, PLAINTEXT)).toBe(FIXED_SIG)
    expect(await signEnvelope(ENVELOPE, PLAINTEXT + 'x')).not.toBe(FIXED_SIG)
  })
})

describe('ENDPOINTS.inboundBridge* 九条路径', () => {
  const NINE = [
    ENDPOINTS.inboundBridgeEvents,
    ENDPOINTS.inboundBridgeReceipts,
    ENDPOINTS.inboundBridgeStatus,
    ENDPOINTS.inboundBridgePoll,
    ENDPOINTS.inboundBridgePair,
    ENDPOINTS.inboundBridgePairRotate('pair-1'),
    ENDPOINTS.inboundBridgePairItem('pair-1'),
    ENDPOINTS.inboundBridgeAllowlist,
    ENDPOINTS.inboundBridgeAudit,
  ]

  it('九条路径与后端 /api/inbound/bridge/* 前缀一致', () => {
    const keys = Object.keys(ENDPOINTS).filter((k) => k.startsWith('inboundBridge'))
    expect(keys).toHaveLength(9)
    expect(NINE).toEqual([
      '/inbound/bridge/events',
      '/inbound/bridge/receipts',
      '/inbound/bridge/status',
      '/inbound/bridge/poll',
      '/inbound/bridge/pair',
      '/inbound/bridge/pair/pair-1/rotate',
      '/inbound/bridge/pair/pair-1',
      '/inbound/bridge/allowlist',
      '/inbound/bridge/audit',
    ])
    for (const path of NINE) {
      expect(`/api${path}`).toMatch(/^\/api\/inbound\/bridge\//)
    }
  })

  it('端点路径不含任何令牌明文/密文/哈希，且 pair id 经过编码', () => {
    for (const path of NINE) {
      expect(path).not.toMatch(/fd_ib_|fd_skill_|private-|token|secret|hash/i)
    }
    expect(ENDPOINTS.inboundBridgePairItem('a/b')).toContain('a%2Fb')
    expect(ENDPOINTS.inboundBridgePairRotate('a/b')).toContain('a%2Fb')
  })
})
