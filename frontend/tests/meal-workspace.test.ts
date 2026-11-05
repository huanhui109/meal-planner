import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { MealContext, MealView } from '@shared/meal'
import { assistantTask } from '@shared/meal'
import Meal from '../src/pages/Meal'
import MainLayout from '../src/components/Layout'

const context: MealContext = {
  meal_date: '2026-11-04', meal_slot: 'dinner', mode: 'cook', servings: 3,
  max_minutes: 60, budget: null, max_spice: 0, avoid: ['花生'],
  vegetarian: false, light: false, use_fridge: true, avoid_recent: true,
}
const base: MealView = {
  context, session_id: 'session', revision: 1,
  proposal: {
    id: 'proposal', title: '番茄炒蛋 · 蒜蓉青菜', source: 'quick', status: 'proposed',
    mode: 'cook', context, servings: 3, reason: '主食与菜一起安排',
    dishes: [
      { key: 'main', name: '番茄炒蛋', role: 'main', ingredients: ['番茄', '鸡蛋'], steps: ['切番茄', '炒鸡蛋'] },
      { key: 'side', name: '蒜蓉青菜', role: 'side', ingredients: ['青菜'], steps: ['洗净青菜'] },
      { key: 'rice', name: '米饭', role: 'staple', ingredients: ['大米'], steps: ['启动电饭煲'] },
    ].map((dish) => ({
      ...dish, role: dish.role as 'main' | 'side' | 'staple', recipe_id: null,
      estimated_minutes: 20, estimated_cost: null, spice: 0, base_servings: null, requirements: [],
    })),
    estimated_minutes: 40, estimated_cost: null, available: [], missing: ['番茄', '鸡蛋', '青菜'],
    protected_avoid: ['花生'], warnings: [], takeout: null, inventory_result: null,
    created_at: null, accepted_at: null, eaten_at: null,
  },
}
const state = { view: base as MealView | null, error: '', loading: false, busy: false }
vi.mock('../src/hooks/useMeal', () => ({
  useMeal: () => ({ ...state, refresh: vi.fn(), propose: vi.fn(), act: vi.fn() }),
}))
const render = () => renderToStaticMarkup(React.createElement(StaticRouter, { location: '/' }, React.createElement(Meal)))
const text = () => render().replace(/<[^>]*>/g, '')

beforeAll(() => { vi.stubGlobal('window', { location: { origin: 'https://meals.example' } }) })
afterAll(() => { vi.unstubAllGlobals() })

describe('这一餐', () => {
  it('shows a complete family meal and identifies rule provenance honestly', () => {
    const html = text()
    for (const expected of ['快速推荐', '番茄炒蛋', '蒜蓉青菜', '米饭', '3 人份', '就吃这个']) expect(html).toContain(expected)
    expect(html).not.toContain('吃过了，记下来')
    expect(html).not.toContain('切番茄')
  })

  it('acceptance reveals execution but does not mark the meal eaten', () => {
    state.view = { ...base, proposal: { ...base.proposal!, status: 'accepted' } }
    const html = render()
    expect(html).toContain('切番茄')
    expect(html).toContain('吃过了，记下来')
    expect(html).toContain('按已知配方用量扣减库存')
    expect(html).not.toContain('checked=""')
    expect(html).not.toContain('撤销吃过记录')
  })

  it('eaten state offers an explicit undo instead of double completion', () => {
    state.view = { ...base, proposal: { ...base.proposal!, status: 'eaten' } }
    expect(text()).toContain('撤销吃过记录')
    expect(text()).not.toContain('吃过了，记下来')
  })

  it('takeout provides ordering notes and search without fabricated merchant details', () => {
    state.view = {
      ...base, proposal: { ...base.proposal!, mode: 'takeout', estimated_minutes: null,
        takeout: { search_term: '米饭套餐', order_note: '3 人份；不辣', search_url: 'https://example.com/search' } },
    }
    expect(text()).toContain('复制点单备注')
    expect(text()).toContain('去搜这一餐')
    expect(text()).not.toContain('参考用时约')
  })

  it('keeps the existing proposal visible on constraint failures', () => {
    state.view = base; state.error = '要求冲突，不会自动放宽忌口'
    expect(text()).toContain(state.error)
    expect(text()).toContain(base.proposal!.title)
    state.error = ''
  })
})

it('has three primary destinations and keeps weekly menus out of navigation', () => {
  const html = renderToStaticMarkup(React.createElement(StaticRouter, { location: '/' }, React.createElement(MainLayout, {
    user: { id: 1, name: '家人', open_id: 'test', avatar_url: null }, children: '内容',
  })))
  for (const name of ['这一餐', '厨房', '记录']) expect(html).toContain(name)
  expect(html).not.toContain('周菜单')
  expect(html).toContain('偏好与助手设置')
})

it('assistant handoff contains context, not an authorization secret', () => {
  const task = assistantTask(base, 'https://meals.example')
  expect(task).toContain('2026-11-04')
  expect(task).toContain('花生')
  expect(task).toContain('只保存建议')
  expect(task).not.toContain('fd_skill_')
  expect(task).not.toContain('Bearer')
})
