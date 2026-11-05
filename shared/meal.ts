export type MealSlotName = 'breakfast' | 'lunch' | 'dinner' | 'late_night'
export type MealMode = 'auto' | 'cook' | 'takeout'
export type MealStatus = 'proposed' | 'accepted' | 'eaten' | 'rejected'

export interface MealContext {
  meal_date: string
  meal_slot: MealSlotName
  mode: MealMode
  servings: number
  max_minutes: number
  budget: number | null
  max_spice: number
  avoid: string[]
  vegetarian: boolean
  light: boolean
  use_fridge: boolean
  avoid_recent: boolean
}

export interface MealDish {
  key: string
  recipe_id: number | null
  name: string
  role: 'complete' | 'main' | 'side' | 'staple' | 'soup'
  ingredients: string[]
  steps: string[]
  estimated_minutes: number
  estimated_cost: number | null
  spice: number
  base_servings: number | null
  requirements: { ingredient_id: number | null; name: string; quantity: number | null; unit: string }[]
}

export interface MealInventoryResult {
  deducted: boolean
  consumed: { name: string; quantity: number; unit: string }[]
  missing: { name: string; quantity: number; unit: string }[]
  unquantified: string[]
  note: string
}

export interface MealProposal {
  id: string
  title: string
  source: 'quick' | 'assistant'
  status: MealStatus
  mode: 'cook' | 'takeout'
  context: MealContext
  servings: number
  dishes: MealDish[]
  reason: string
  assistant_note?: string
  estimated_minutes: number | null
  estimated_cost: number | null
  available: string[]
  missing: string[]
  protected_avoid: string[]
  warnings: string[]
  takeout: { search_term: string; search_url: string; order_note: string } | null
  inventory_result: MealInventoryResult | null
  created_at: string | null
  accepted_at: string | null
  eaten_at: string | null
}

export interface MealView {
  context: MealContext
  session_id: string | null
  revision: number
  proposal: MealProposal | null
}

export interface MealHistoryItem extends MealProposal {
  meal_date: string
  meal_slot: MealSlotName
}

export interface AssistantGrant {
  id: string
  name: string
  scopes: string[]
  created_at: string | null
  expires_at: string
  revoked_at: string | null
}

export interface WorkBuddyStatus {
  configured: boolean
  connected: boolean
  online: boolean | null
  state: 'not_configured' | 'disconnected' | 'online' | 'offline' | 'unavailable'
  message: string
}

export interface AssistantAdjustment {
  id: string
  instruction: string
  context: MealContext
  status: 'sending' | 'waiting' | 'completed' | 'failed' | 'cancelled'
  phase: 'context' | 'proposal'
  error: string | null
  proposal_id: string | null
  poll_after_ms: number
  expires_at: string
}

export interface AssistantAdjustmentRequest {
  request_id: string
  instruction: string
  context: MealContext
  expected_revision: number
}

export const adjustmentPending = (job: AssistantAdjustment | null) =>
  job?.status === 'sending' || job?.status === 'waiting'

export function adjustmentLabel(job: AssistantAdjustment | null): string {
  if (!job) return '正在发送给助手'
  if (job.status === 'completed') return '新方案已保存，等你决定'
  if (job.status === 'cancelled') return '本次调整已取消'
  if (job.status === 'failed') return '本次调整未完成'
  if (job.status === 'sending') return '正在发送给助手'
  return job.phase === 'context' ? '助手正在理解你的要求' : '助手正在搭配这一餐'
}

export const mealSlotLabels: Record<MealSlotName, string> = {
  breakfast: '早餐', lunch: '午餐', dinner: '晚餐', late_night: '夜宵',
}

export const mealStatusLabels: Record<MealStatus, string> = {
  proposed: '待决定', accepted: '已选定', eaten: '已吃过', rejected: '已换掉',
}

export function assistantTask(view: MealView, origin: string, instruction = ''): string {
  const context = view.context
  return [
    '请使用饭决 Skill 调整这一餐，只保存建议，不代替我确认用餐或扣库存。',
    `饭决地址：${origin}`,
    `用餐日期：${context.meal_date}，餐次：${context.meal_slot}，${context.servings} 人。`,
    `当前条件：${JSON.stringify(context)}`,
    view.proposal ? `当前建议：${view.proposal.title}` : '当前还没有合适的建议。',
    '请先读取最新上下文和候选，遵守已保存的忌口；无法满足时说明原因。',
    '我的调整要求：',
    instruction.trim(),
  ].join('\n')
}
