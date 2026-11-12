import type { DishCategoryCode } from './dish-category'

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
  /** 长期口味里的互斥大类; null/缺省 = 不限。方案内类别一致仍是硬规则 */
  dish_category?: DishCategoryCode | null
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
  /** 服务端下发的互斥大类; 可选是为了兼容旧 fixture 与旧方案快照 */
  dish_category?: DishCategoryCode
  dish_category_label?: string
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
  status: 'sending' | 'waiting' | 'calling' | 'completed' | 'failed' | 'cancelled'
  phase: 'context' | 'proposal'
  error: string | null
  proposal_id: string | null
  /** 后端 view() 会返回；'model' = 应用内直接模型请求 */
  source?: string
  /** 本次是否触发候选补全、补了什么（未触发时为空串） */
  generation_note?: string
  poll_after_ms: number
  expires_at: string
}

/**
 * 应用内候选菜品技能 fandecide-candidates 的结构化输出。
 * 字段与 skills/fandecide-candidates/contract.json 一一对应，可反向写入 recipe 表。
 */
export interface DishCandidate {
  name: string
  cuisine: string
  category: string
  main_ingredient: string
  cook_minutes: number | null
  spice_level: number | null
  is_light: boolean | null
  ingredients: string[]
  quick_steps: string[]
  steps: string[]
  reality_basis: string
  /** 仅 persist=true 且服务端裁决通过入池时返回 */
  recipe_id?: number
  key?: string
}

/** POST /assistant/candidates：一段模糊描述 → 默认 4 个（3-5）候选 */
export interface DishCandidateRequest {
  description: string
  /** 3-5，缺省 4 */
  count?: number
  context?: Partial<MealContext>
  exclude_names?: string[]
  named_dish?: string
  /** true = 服务端按「不得杜撰」校验后决定是否写入候选池 */
  persist?: boolean
}

export interface DishCandidateResult {
  skill: string
  count: number
  candidates: DishCandidate[]
  persisted: string[]
  rejected: string[]
  reason: string
  degraded: boolean
}

export interface AssistantAdjustmentRequest {
  request_id: string
  instruction: string
  context: MealContext
  expected_revision: number
}

/** 本机 WorkBuddy 目录里的一个模型（后端只读取插件目录, 绝不编造价格/模型） */
export interface ModelCatalogItem {
  id: string
  name: string
  /** 上游积分倍率原文（如 "0.5"）；空串表示目录未标注 */
  credits: string
  free: boolean
  badges: string[]
  context_window: number | null
  max_tokens: number | null
  supports_images: boolean
  reasoning: { supported_efforts: string[] }
}

/** GET /assistant/model 的响应（SuccessResponse 解包后的 data） */
export interface ModelConnectionStatus {
  available: boolean
  region: string
  model: string
  message: string
  /** 本机 WorkBuddy 目录里可选的模型; 目录不可读时为空数组 */
  catalog: ModelCatalogItem[]
  /** 用户显式选择; 空串表示「自动（优先免费）」 */
  selected: string
  /** 是否处于自动选择 */
  auto: boolean
  /** 之前选的模型是否仍在当前目录里; false 时界面要如实提示 */
  selection_available: boolean
}

/**
 * `/assistant/login` 系列的返回（SuccessResponse 解包后的 data）。
 *
 * 一个会话跨三态: 发起 (ok + login_id + verification_uri)、等待 (ok + done:false)、
 * 终态 (done:true 且 ok 为真=成功 / 假=失败)。失败也可能出现在发起阶段。
 */
export interface LoginSession {
  ok: boolean
  done?: boolean
  login_id?: string
  region?: string
  verification_uri?: string
  expires_in?: number
  account_id?: string
  nickname?: string
  message?: string
  error?: string
}

export const adjustmentPending = (job: AssistantAdjustment | null) =>
  job?.status === 'sending' || job?.status === 'waiting' || job?.status === 'calling'

export function adjustmentLabel(job: AssistantAdjustment | null): string {
  if (!job) return '正在发送给助手'
  if (job.status === 'completed') return '新方案已保存，等你决定'
  if (job.status === 'cancelled') return '本次调整已取消'
  if (job.status === 'failed') return '本次调整未完成'
  if (job.status === 'calling') return '正在向本机 WorkBuddy 模型请求'
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
