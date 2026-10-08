// 与 meal-planner 后端共用的数据形状（只摘前端要用的字段, 不引后端类型）

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

// ---------- 周菜单 ----------
export interface MenuRecipeIngredient {
  name: string
  quantity: number | null
  unit: string
  reference_price: number | null
}

export interface MenuRecipe {
  id: number
  name: string
  cuisine: string
  difficulty: number
  cook_minutes: number
  calories: number
  protein_g: number
  carb_g: number
  fat_g: number
  steps: string[]
  source: string
  ingredients: MenuRecipeIngredient[]
}

export interface MenuMeal {
  id: number
  meal_type: string
  meal_label: string
  is_locked: boolean
  is_cooked: boolean
  cook_mode: string
  estimated_cost: number | null
  recipe: MenuRecipe | null
}

export interface MenuDay {
  date: string
  weekday: string
  day_type: string
  estimated_cost: number
  meals: MenuMeal[]
}

export interface MenuTotals {
  estimated_cost: number
  unpriced_items: number
  meal_count: number
  day_count: number
  cooked_count: number
}

export interface MenuBudget {
  passed: boolean
  total_estimated: number | null
  budget_limit: number | null
  over_amount: number | null
  suggestions: string[]
}

export interface MenuData {
  id: number
  week_start_date: string
  status: string
  budget: MenuBudget | null
  totals: MenuTotals
  days: MenuDay[]
}

// ---------- 采购清单 ----------
export interface ShoppingItem {
  ingredient_id: number
  name: string
  category: string
  unit: string
  required_quantity: number | null
  reference_price: number | null
  quantitative: boolean
  in_stock_quantity: number
  deficit: number | null
  have_enough: boolean
  unit_mismatch: boolean
}

export interface ShoppingData {
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

// ---------- 冰箱 ----------
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

export interface InventoryList {
  total: number
  expiring_count: number
  items: InventoryItem[]
}

// ---------- 偏好 ----------
export interface PreferenceSummary {
  household?: HouseholdPref | null
  diet?: DietPref | null
  allergy?: AllergyPref | null
  health_goal?: HealthGoalPref | null
  budget?: BudgetPref | null
}

export interface HouseholdPref {
  member_count: number
  meals_per_day: number
  kitchen_equipments: string[]
  weekday_cook_minutes: number
  weekend_cook_minutes: number
}

export interface DietPref {
  cuisines: string[]
  spice_level: string
  flavor_preference: string
  staple_preference: string
  scene_tags: string[]
}

export interface AllergyPref {
  allergens: string[]
  avoid_ingredients: string[]
  dietary_restrictions: string[]
}

export interface HealthGoalPref {
  goal_type: string
  daily_calories: number
  protein_pct: number
  carb_pct: number
  fat_pct: number
}

export interface BudgetPref {
  weekday_daily_budget: number
  weekend_daily_budget: number
  weekly_cap: number
  min_meal_budget: number
  takeout_reference_price: number
}
