import apiClient, { unwrap } from './client'
import ENDPOINTS from '@shared/endpoints'
import type {
  AssistantAdjustment, AssistantAdjustmentRequest, AssistantGrant, DishCandidateRequest,
  DishCandidateResult, LoginSession, MealContext, MealHistoryItem, MealSlotName, MealView,
  ModelConnectionStatus, WorkBuddyStatus,
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
export const getModelStatus = () => connectionRequest((signal) =>
  unwrap<ModelConnectionStatus>(apiClient.get('/assistant/model', { signal })))
/**
 * 保存模型选择（空串 = 自动，优先免费）。
 *
 * 普通写入操作，不走 connectionRequest：15s 上限只用于探测本机助手连接，
 * 而 422 的文案后端已经写成可读中文，界面要原样展示。
 */
export const chooseModel = (model: string, region = '') =>
  unwrap<{ selected: string; effective: string; auto: boolean }>(
    apiClient.post('/assistant/model', { model, region }))
export const startWorkBuddyLogin = (region: 'cn' | 'global') =>
  connectionRequest((signal) => unwrap<LoginSession>(
    apiClient.post('/assistant/login', { region }, { signal })))
export const pollWorkBuddyLogin = (loginId: string, region: 'cn' | 'global') =>
  connectionRequest((signal) => unwrap<LoginSession>(
    apiClient.get(`/assistant/login/${encodeURIComponent(loginId)}`, { params: { region }, signal })))
export const logoutWorkBuddyAccount = (region: 'cn' | 'global') =>
  connectionRequest((signal) => unwrap<{ removed: number }>(
    apiClient.delete('/assistant/login', { params: { region }, signal })))
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

/**
 * 应用内候选菜品技能：单跳低延迟，一次模型请求返回默认 4 个（3-5）结构化候选。
 * 与「交给 AI 调整」互补：那条链路负责组合一餐，这里只拿候选、不建任务、不轮询。
 */
export const requestDishCandidates = (request: DishCandidateRequest) =>
  unwrap<DishCandidateResult>(apiClient.post(ENDPOINTS.assistantCandidates, request))
