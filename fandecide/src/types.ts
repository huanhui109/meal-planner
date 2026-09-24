// 与 meal-planner 后端共用的数据形状（只摘决策屏要用的字段, 不引后端类型）

export interface SuccessEnvelope<T> {
  code: number
  message: string
  data: T
}

export interface DecideDish {
  recipe_id?: number | null
  name: string
  cuisine: string
  category: string
  cover_text: string
  cook_minutes: number
  calories: number
  difficulty: number
  main_ingredient: string
  ingredients: string[]
  steps: string[]
}

export interface DecisionResult {
  id: number
  dish: DecideDish
  reason: string
  meal_slot: string
  meal_slot_label: string
  source: string
  weather: Record<string, unknown>
  advice?: string | null
  relaxed: boolean
  decided_at: string
}

export interface DecideRecentItem {
  id: number
  dish_name: string
  meal_slot: string
  reason?: string | null
  accepted?: boolean | null
  decision_date: string
}

export interface CurrentUser {
  id: number
  name: string
  avatar_url?: string | null
  role: string
}
