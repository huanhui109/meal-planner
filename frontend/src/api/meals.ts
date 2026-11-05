import apiClient, { unwrap } from './client'
import type {
  AssistantAdjustment, AssistantAdjustmentRequest, AssistantGrant,
  MealContext, MealHistoryItem, MealSlotName, MealView, WorkBuddyStatus,
} from '@shared/meal'

export const getCurrentMeal = (slot?: MealSlotName, date?: string, signal?: AbortSignal) =>
  unwrap<MealView>(apiClient.get('/meals/current', { params: { meal_slot: slot, meal_date: date }, signal }))

export const proposeMeal = (context: Partial<MealContext>, revision: number) =>
  unwrap<MealView>(apiClient.post('/meals/propose', { context, expected_revision: revision }))

export const actOnMeal = (
  id: string, action: 'accept' | 'complete' | 'undo', revision: number, deduct = false,
) => unwrap<MealView>(apiClient.post(`/meals/${encodeURIComponent(id)}/${action}`, {
  expected_revision: revision, deduct_inventory: deduct,
}))

export const recordMealView = (id: string) => apiClient.post(`/meals/${encodeURIComponent(id)}/viewed`)
export const getMealHistory = () => unwrap<MealHistoryItem[]>(apiClient.get('/meals/history'))

async function connectionRequest<T>(request: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout>
  // Bound auth-refresh retries as well as the first HTTP request.
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort()
      reject(new Error('助手连接请求超时，请重试；操作结果可刷新确认'))
    }, 15000)
  })
  try { return await Promise.race([request(controller.signal), deadline]) }
  finally { clearTimeout(timer!) }
}

export const getAssistantGrants = () => connectionRequest((signal) =>
  unwrap<AssistantGrant[]>(apiClient.get('/assistant/grants', { signal })))
export const createAssistantGrant = () =>
  connectionRequest((signal) => unwrap<AssistantGrant & { token: string }>(
    apiClient.post('/assistant/grants', {}, { signal })))
export const revokeAssistantGrant = (id: string) =>
  connectionRequest((signal) => apiClient.delete(`/assistant/grants/${encodeURIComponent(id)}`, { signal }))

export const getWorkBuddyStatus = () => connectionRequest((signal) =>
  unwrap<WorkBuddyStatus>(apiClient.get('/assistant/workbuddy', { signal })))
export const authorizeWorkBuddy = () =>
  connectionRequest((signal) => unwrap<{ url: string }>(
    apiClient.post('/assistant/workbuddy/authorize', undefined, { signal })))
export const disconnectWorkBuddy = () => connectionRequest((signal) =>
  apiClient.delete('/assistant/workbuddy', { signal }))
export const startAssistantAdjustment = (request: AssistantAdjustmentRequest) =>
  unwrap<AssistantAdjustment>(apiClient.post('/assistant/adjustments', request))
export const getAssistantAdjustment = (id: string) =>
  unwrap<AssistantAdjustment>(apiClient.get(`/assistant/adjustments/${encodeURIComponent(id)}`))
export const getCurrentAdjustment = (date: string, slot: MealSlotName) =>
  unwrap<AssistantAdjustment | null>(apiClient.get('/assistant/adjustments/current', {
    params: { meal_date: date, meal_slot: slot },
  }))
export const cancelAssistantAdjustment = (id: string) =>
  unwrap<AssistantAdjustment>(apiClient.post(`/assistant/adjustments/${encodeURIComponent(id)}/cancel`))
