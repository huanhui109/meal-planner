import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AssistantAdjustment, MealContext, MealView } from '@shared/meal'
import { adjustmentLabel, adjustmentPending, assistantTask } from '@shared/meal'
import {
  cancelAssistantAdjustment, getAssistantAdjustment, getCurrentAdjustment,
  startAssistantAdjustment,
} from '../src/api/meals'

const transport = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), delete: vi.fn(),
}))
vi.mock('../src/api/client', () => ({
  default: transport,
  unwrap: async (response: Promise<{ data: unknown }>) => (await response).data,
}))

const context: MealContext = {
  meal_date: '2026-11-04', meal_slot: 'dinner', mode: 'auto', servings: 2,
  max_minutes: 30, max_spice: 2, budget: null, avoid: ['花生'],
  vegetarian: false, light: false, use_fridge: false, avoid_recent: true,
}
const view: MealView = { context, revision: 7, session_id: 'session', proposal: null }
const job: AssistantAdjustment = {
  id: 'request-id', instruction: '两个人，不开火', context, status: 'waiting',
  phase: 'context', error: null, proposal_id: null, poll_after_ms: 3000,
  expires_at: '2026-11-04T21:00:00',
}

beforeEach(() => {
  vi.clearAllMocks()
  transport.get.mockResolvedValue({ data: job })
  transport.post.mockResolvedValue({ data: job })
})

describe('助手调整状态', () => {
  it('only sending and waiting block another adjustment', () => {
    expect(adjustmentPending(null)).toBe(false)
    for (const status of ['sending', 'waiting'] as const) {
      expect(adjustmentPending({ ...job, status })).toBe(true)
    }
    for (const status of ['completed', 'failed', 'cancelled'] as const) {
      expect(adjustmentPending({ ...job, status })).toBe(false)
    }
  })

  it('distinguishes understanding from choosing and success from acceptance', () => {
    expect(adjustmentLabel(job)).toContain('理解')
    expect(adjustmentLabel({ ...job, phase: 'proposal' })).toContain('搭配')
    expect(adjustmentLabel({ ...job, status: 'completed' })).toContain('等你决定')
    expect(adjustmentLabel({ ...job, status: 'cancelled' })).toContain('取消')
    expect(adjustmentLabel({ ...job, status: 'failed' })).toContain('未完成')
  })

  it('copy fallback includes the edited request and context but no credentials', () => {
    const text = assistantTask(view, 'https://meals.example', '  不开火，预算六十元  ')
    expect(text).toContain('不开火，预算六十元')
    expect(text).toContain('花生')
    expect(text).toContain('只保存建议')
    expect(text).not.toContain('fd_skill_')
    expect(text).not.toContain('Bearer')
  })
})

describe('助手调整 API', () => {
  it('sends one idempotency key, an edited instruction and a fixed meal revision', async () => {
    const request = {
      request_id: 'stable-id', instruction: '两个人，不开火',
      context: view.context, expected_revision: view.revision,
    }
    expect(await startAssistantAdjustment(request)).toEqual(job)
    expect(transport.post).toHaveBeenCalledExactlyOnceWith('/assistant/adjustments', request)
  })

  it('restores only the current date and slot and safely encodes receipt IDs', async () => {
    await getCurrentAdjustment(context.meal_date, context.meal_slot)
    expect(transport.get).toHaveBeenCalledWith('/assistant/adjustments/current', {
      params: { meal_date: context.meal_date, meal_slot: 'dinner' },
    })
    await getAssistantAdjustment('id/other')
    expect(transport.get).toHaveBeenCalledWith('/assistant/adjustments/id%2Fother')
    await cancelAssistantAdjustment('id/other')
    expect(transport.post).toHaveBeenCalledWith('/assistant/adjustments/id%2Fother/cancel')
  })
})
