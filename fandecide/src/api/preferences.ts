import { apiGet, apiPut } from './client'
import type { PreferenceSummary } from '@/types'

// 偏好: 一次性拿全部分组, 各分组独立 PUT 更新。

export function getPreferenceSummary(): Promise<PreferenceSummary> {
  return apiGet<PreferenceSummary>('/api/preferences/summary')
}

export function updateHousehold(data: Record<string, unknown>): Promise<unknown> {
  return apiPut('/api/preferences/household', data)
}

export function updateDiet(data: Record<string, unknown>): Promise<unknown> {
  return apiPut('/api/preferences/diet', data)
}

export function updateAllergy(data: Record<string, unknown>): Promise<unknown> {
  return apiPut('/api/preferences/allergy', data)
}

export function updateHealthGoal(data: Record<string, unknown>): Promise<unknown> {
  return apiPut('/api/preferences/health-goal', data)
}

export function updateBudget(data: Record<string, unknown>): Promise<unknown> {
  return apiPut('/api/preferences/budget', data)
}
