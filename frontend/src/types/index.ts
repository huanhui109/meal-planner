/** 后端统一响应信封 */
export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

/** 当前登录用户 */
export interface CurrentUser {
  id: number
  name: string
  open_id: string
  avatar_url: string | null
}

/** 当前可用的登录方式 */
export interface AuthProviders {
  feishu: boolean
  dev_login: boolean
}

/** 用户偏好相关类型 */
export interface Household {
  id?: number
  member_count: number
  meals_per_day: number
  kitchen_equipments: string[]
  weekday_cook_minutes: number
  weekend_cook_minutes: number
}

export interface DietPreference {
  id?: number
  cuisines: string[]
  spice_level: number
  flavor_preference: string
  staple_preference: string
}

export interface AllergyRestriction {
  id?: number
  allergens: string[]
  avoid_ingredients: string[]
  dietary_restrictions: string
}

export interface HealthGoal {
  id?: number
  goal_type: string
  daily_calories: number
  protein_pct: number
  carb_pct: number
  fat_pct: number
}

export interface Budget {
  id?: number
  weekday_daily_budget: number
  weekend_daily_budget: number
  weekly_cap: number | null
  min_meal_budget: number
}

export interface UserPreferenceSummary {
  household: Household | null
  diet_preference: DietPreference | null
  allergy_restriction: AllergyRestriction | null
  health_goal: HealthGoal | null
  budget: Budget | null
}

/** 菜单相关类型 */
export type MenuStatus = 'draft' | 'confirmed' | 'active' | 'completed'
export type GenerationStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface RecipeIngredientDetail {
  name: string
  quantity: number | null
  unit: string
  reference_price: number | null
}

export interface RecipeDetail {
  id: number
  name: string
  cuisine: string | null
  difficulty: number | null
  cook_minutes: number | null
  calories: number | null
  protein_g: number | null
  carb_g: number | null
  fat_g: number | null
  steps: string | null
  source: string | null
  ingredients: RecipeIngredientDetail[]
}

export interface MealDetail {
  id: number
  meal_type: string
  meal_label: string
  is_locked: boolean
  is_cooked: boolean
  cook_mode: string
  estimated_cost: number | null
  recipe: RecipeDetail | null
}

export interface MenuDay {
  date: string
  weekday: number
  day_type: 'weekday' | 'weekend'
  estimated_cost: number
  meals: MealDetail[]
}

export interface DailyNutrition {
  date: string
  calories: number
  protein_g: number
  carb_g: number
  fat_g: number
  protein_pct: number
  carb_pct: number
  fat_pct: number
  meal_count: number
}

export interface NutritionSummary {
  passed: boolean
  days_count: number
  weekly_avg_calories: number
  target_calories: number | null
  issues: string[]
  daily: DailyNutrition[]
}

export interface BudgetSummary {
  passed: boolean
  total_estimated: number
  budget_limit: number
  over_amount: number
  suggestions: string[]
}

export interface MenuTotals {
  estimated_cost: number
  unpriced_items: number
  meal_count: number
  day_count: number
  cooked_count: number
}

export interface MenuDetail {
  id: number
  user_id: number
  week_start_date: string
  status: MenuStatus
  created_at: string | null
  updated_at: string | null
  totals: MenuTotals
  nutrition: NutritionSummary
  budget: BudgetSummary
  days: MenuDay[]
}

export interface GenerateAccepted {
  task_id: number | null
  menu_id: number | null
  week_start_date: string
  reused: boolean
  status: string
}

export interface GenerationTask {
  task_id: number
  status: GenerationStatus
  menu_id: number | null
  week_start_date: string
  error: string | null
  created_at: string | null
  finished_at: string | null
}

/** 采购清单 */
export interface ShoppingItem {
  ingredient_id: number
  name: string
  category: string
  unit: string
  required_quantity: number | null
  in_stock_quantity: number
  deficit: number | null
  have_enough: boolean
  quantitative: boolean
  unit_mismatch: boolean
}

export interface ShoppingList {
  menu_id: number
  week_start_date: string
  summary: {
    total_count: number
    to_buy_count: number
    have_count: number
    unit_mismatch_count: number
  }
  items: ShoppingItem[]
}

/** 库存 */
export interface InventoryItem {
  id: number
  ingredient_id: number
  ingredient_name: string
  category: string | null
  quantity: number
  unit: string
  purchase_date: string | null
  expiry_date: string | null
  days_left: number | null
  expiring_soon: boolean
  source: string | null
}

/** 标记已做的扣减结果 */
export interface ConsumeResult {
  item_id: number
  already_cooked: boolean
  consumed: Array<{
    ingredient_name: string
    inventory_id: number
    quantity: number
    unit: string
  }>
  missing: Array<{
    ingredient_name: string
    required_quantity: number | null
    unit: string
    consumed_quantity?: number
    deficit?: number
    reason?: string
  }>
}

/** 商品 (二期采集) */
export interface Product {
  id: number
  name: string
  category: string | null
  price: number
  unit: string | null
  in_stock: boolean
  price_changed: boolean
}
