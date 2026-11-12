import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AssistantGrant } from '@shared/meal'
import AssistantConnection from '../src/components/AssistantConnection'
import { authorizationTarget, grantState } from '../src/lib/assistantConnection'
import {
  authorizeWorkBuddy, chooseModel, createAssistantGrant, disconnectWorkBuddy,
  getAssistantGrants, getModelStatus, getWorkBuddyStatus, pollWorkBuddyLogin,
  revokeAssistantGrant, startWorkBuddyLogin,
} from '../src/api/meals'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('../src/api/client', () => ({
  default: transport,
  unwrap: async (response: Promise<{ data: unknown }>) => (await response).data,
}))

const grant: AssistantGrant = {
  id: 'grant', name: '饭决 Skill', scopes: ['meal:read', 'meal:propose'],
  created_at: null, expires_at: '2026-11-05T00:00:00', revoked_at: null,
}

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => { vi.useRealTimers() })

describe('统一助手连接入口', () => {
  it('is actionable even before host configuration or the initial status request completes', () => {
    const html = renderToStaticMarkup(React.createElement(StaticRouter, { location: '/me' },
      React.createElement(AssistantConnection)))
    expect(html).toContain('<h2>助手连接</h2>')
    expect(html).not.toContain('<h2>Skill 访问凭据</h2>')
    const connect = html.match(/<button\b[^>]*>[\s\S]*?连接助手<\/button>/g)?.at(-1)
    expect(connect).toBeDefined()
    // The separate refresh button may be busy; the setup entry must never depend on it.
    expect(connect?.slice(connect.lastIndexOf('<button'))).not.toContain('disabled')
    expect(html).toContain('正在检查网页直发')
  })

  it('renders a dedicated, truthful local-model status line on the unified card', async () => {
    const model = { available: true, region: 'cn', model: 'hy4free', message: '本机已登录' }
    // getModelStatus shares the mocked transport and unwraps the SuccessResponse data.
    // mockResolvedValueOnce keeps later tests on a pristine vi.fn().
    transport.get.mockResolvedValueOnce({ data: model })
    await expect(getModelStatus()).resolves.toEqual(model)
    const html = renderToStaticMarkup(React.createElement(StaticRouter, { location: '/me' },
      React.createElement(AssistantConnection)))
    // The card has its own model line, separate from hostMessage.
    expect(html).toContain('本机 WorkBuddy 直连模型')
    // Static (server) render has no completed effect: show the real pending state,
    // never a fabricated "online" claim before the check actually resolves.
    expect(html).toContain('正在确认本机模型状态')
    expect(html).toContain('正在检查网页直发')
  })

  it('does not treat a valid grant as proof of a connected host', () => {
    const now = Date.parse('2026-11-04T15:59:59Z')
    expect(grantState(grant, now)).toBe('active')
    expect(grantState(grant, now + 1000)).toBe('expired')
    expect(grantState({ ...grant, revoked_at: '2026-11-04' }, now)).toBe('revoked')
    expect(grantState({ ...grant, expires_at: 'invalid' }, now)).toBe('expired')
  })

  it('supports explicitly zoned expiry timestamps independent of the browser timezone', () => {
    const now = Date.parse('2026-11-04T16:00:00Z')
    expect(grantState({ ...grant, expires_at: '2026-11-05T00:00:00+08:00' }, now)).toBe('expired')
    expect(grantState({ ...grant, expires_at: '2026-11-04T16:00:01Z' }, now)).toBe('active')
  })
})

describe('WorkBuddy 授权地址', () => {
  it('allows only the existing official authorization endpoint', () => {
    const url = 'https://www.workbuddy.cn/openapi/v2/authorize?state=example'
    expect(authorizationTarget(url)).toBe(url)
  })
  it.each([
    'https://www.workbuddy.cn.attacker.example/openapi/v2/authorize',
    'http://www.workbuddy.cn/openapi/v2/authorize',
    'https://www.workbuddy.cn/another-path',
    'https://user:password@www.workbuddy.cn/openapi/v2/authorize',
    '/openapi/v2/authorize',
    'javascript:alert(1)',
  ])('rejects unsafe redirects: %s', (url) => {
    expect(() => authorizationTarget(url)).toThrow()
  })
})

describe('连接请求的加载上限', () => {
  it.each([
    ['host status', getWorkBuddyStatus, 'get'],
    ['grants', getAssistantGrants, 'get'],
    ['authorization', authorizeWorkBuddy, 'post'],
    ['create grant', createAssistantGrant, 'post'],
    ['disconnect', disconnectWorkBuddy, 'delete'],
    ['revoke grant', () => revokeAssistantGrant('a/b'), 'delete'],
  ] as const)('bounds %s even when the transport never settles, and does not retry', async (_name, request, method) => {
    vi.useFakeTimers()
    transport[method].mockImplementation(() => new Promise(() => {}))
    const result = request()
    const rejected = expect(result).rejects.toThrow('助手连接请求超时')
    await vi.advanceTimersByTimeAsync(15000)
    await rejected
    expect(transport[method]).toHaveBeenCalledTimes(1)
    const call = transport[method].mock.calls[0]
    const config = call.at(-1) as { signal: AbortSignal }
    expect(config.signal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('clears the deadline on success and preserves scoped credential creation', async () => {
    vi.useFakeTimers()
    transport.post.mockResolvedValue({ data: { ...grant, token: 'one-time-test-token' } })
    expect((await createAssistantGrant()).token).toBe('one-time-test-token')
    expect(transport.post).toHaveBeenCalledWith('/assistant/grants', {}, { signal: expect.any(AbortSignal) })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('surfaces a recoverable request error without waiting for the deadline', async () => {
    vi.useFakeTimers()
    transport.get.mockRejectedValue(new Error('连接暂不可用'))
    await expect(getWorkBuddyStatus()).rejects.toThrow('连接暂不可用')
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('模型选择与重新登录', () => {
  it('POSTs the explicit model choice and the empty region without the connection deadline', async () => {
    transport.post.mockResolvedValue({ data: { selected: 'kimi-k3-1', effective: 'kimi-k3-1', auto: false } })
    await expect(chooseModel('kimi-k3-1')).resolves.toEqual({
      selected: 'kimi-k3-1', effective: 'kimi-k3-1', auto: false,
    })
    expect(transport.post).toHaveBeenCalledTimes(1)
    expect(transport.post).toHaveBeenCalledWith('/assistant/model', { model: 'kimi-k3-1', region: '' })
    // 普通写入操作: 不包 connectionRequest, 所以没有 AbortSignal 这个配置键。
    expect(transport.post.mock.calls[0]).toHaveLength(2)
  })

  it('keeps GET /assistant/model on the 15s deadline pattern', async () => {
    transport.get.mockResolvedValue({ data: { available: true, region: 'cn', model: 'hy4free' } })
    await getModelStatus()
    expect(transport.get).toHaveBeenCalledTimes(1)
    expect(transport.get).toHaveBeenCalledWith('/assistant/model', { signal: expect.any(AbortSignal) })
  })

  it('starts a CN login with a signal and bounds it when the transport never settles', async () => {
    vi.useFakeTimers()
    transport.post.mockImplementation(() => new Promise(() => {}))
    const result = startWorkBuddyLogin('cn')
    const rejected = expect(result).rejects.toThrow('助手连接请求超时')
    await vi.advanceTimersByTimeAsync(15000)
    await rejected
    expect(transport.post).toHaveBeenCalledTimes(1)
    expect(transport.post).toHaveBeenCalledWith('/assistant/login', { region: 'cn' }, {
      signal: expect.any(AbortSignal),
    })
    const config = transport.post.mock.calls[0].at(-1) as { signal: AbortSignal }
    expect(config.signal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('polls a login by its encoded id with the region as a query param', async () => {
    transport.get.mockResolvedValue({ data: { ok: true, done: false, message: '等待授权' } })
    await expect(pollWorkBuddyLogin('id/x', 'cn')).resolves.toEqual({
      ok: true, done: false, message: '等待授权',
    })
    expect(transport.get).toHaveBeenCalledTimes(1)
    const [url, config] = transport.get.mock.calls[0] as [string, { params: unknown; signal: AbortSignal }]
    expect(url).toBe('/assistant/login/id%2Fx')
    expect(config.params).toEqual({ region: 'cn' })
    expect(config.signal).toBeInstanceOf(AbortSignal)
  })
})

describe('模型连接状态指示点', () => {
  it('renders a grey dot labelled 检测中 before the model status resolves', () => {
    const html = renderToStaticMarkup(React.createElement(StaticRouter, { location: '/me' },
      React.createElement(AssistantConnection)))
    // 首帧 modelStatus 为 null: 只能如实显示"检测中"的灰点，不能提前变绿。
    expect(html).toContain('模型选择')
    expect(html).toContain('检测中')
    expect(html).toContain('meal-connection-dot')
    // 绿点的 class 只应出现在真正在线时；首帧不允许出现。
    expect(html).not.toContain('meal-connection-dot online')
  })

  it('labels the pending login block and explains the manual authorization fallback', async () => {
    transport.post.mockResolvedValue({
      data: { ok: true, login_id: 'wbo_x', region: 'cn', verification_uri: 'https://www.codebuddy.cn/login?state=s', expires_in: 600 },
    })
    transport.get.mockResolvedValue({ data: { available: false, region: '', model: '', message: '未连接' } })
    // The dialog-opened state is internal; assert the API contract the UI consumes
    // so a missing field can't silently break the prompt.
    const started = await startWorkBuddyLogin('cn')
    expect(started).toMatchObject({ ok: true, login_id: 'wbo_x', region: 'cn' })
    expect(started.verification_uri).toContain('codebuddy.cn')
  })
})
