/**
 * 前后端共享类型 - H5 与小程序都从这里取, 避免两套定义各自漂移
 */
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
  /** 是否已配置微信小程序 (决定小程序登录页要不要显示"微信一键登录") */
  wechat: boolean
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
  min_meal_budget: number | null
  /** 一顿外卖的参考价 (元); 今日页可以直接改, 会记住 */
  takeout_reference_price: number
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
  /** 仅「换一道」接口会带上: 这次换菜走了哪条路径 */
  replacement?: ReplacementInfo
}

export interface ReplacementInfo {
  source: 'local' | 'ai' | 'restore' | 'manual'
  recipe_id: number | null
  recipe_name: string | null
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
  /** 食材参考单价 (元/标准单位); 没有参考价时为 null, 合计不含它 */
  reference_price?: number | null
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

/** ===== V2.0: 今日页 / 补单 / 外卖对比 / 自动化 ===== */

/** 补单建议里的一行 (缺口食材或凑单品) */
export interface OrderLine {
  ingredient_id: number | null
  name: string
  category: string
  quantity: number | null
  unit: string
  unit_price: number | null
  estimated_price: number | null
  quantitative: boolean
  is_topup: boolean
}

/** F6.3 补单决策 */
export interface OrderSuggestion {
  missing_count: number
  items: OrderLine[]
  estimated_total: number
  unpriced_count: number
  min_order_amount: number
  reaches_min_order: boolean
  /** 距起送价还差多少 (已够则为 0) */
  topup_amount: number
  within_budget: boolean | null
  budget_remaining: number | null
  order_link: string
  links: Array<{ platform: string; label: string; url: string }>
  miniapp_app_id: string | null
  platform: string
  note: string
}

/** F4 自做 vs 外卖 */
export interface TakeoutComparison {
  homemade: { cost: number | null; minutes: number | null; label: string; tone: string }
  takeout: { cost: number | null; minutes: number | null; label: string; source: string }
  saving: number | null
  recommended: 'homemade' | 'takeout' | 'either'
  reasons: string[]
  note: string
  budget_remaining: number | null
  budget_remaining_after_takeout: number | null
  budget_daily: number | null
  spent_today: number
  link: string
  link_label: string
  platform: string
  miniapp_app_id: string | null
}

/** 今日流程时间线的一步 */
export interface TimelineEntry {
  key: 'menu_push' | 'stock_check' | 'cook_deduct' | string
  time: string
  label: string
  status: 'sent' | 'pending' | 'skipped' | 'failed'
  detail: string
}

/** 今晚这一餐 (含做法与外卖对比) */
export interface TonightMeal {
  meal_id: number | null
  meal_type: string
  meal_label: string
  name: string
  is_locked: boolean
  is_cooked: boolean
  servings: number | null
  cook_minutes: number | null
  calories: number | null
  protein_g: number | null
  estimated_cost: number | null
  step_count: number
  ingredients: RecipeIngredientDetail[]
  steps: string | null
  uses_expiring: Array<{ ingredient_name: string; days_left: number }>
  takeout: TakeoutComparison | null
}

/** 今日页顶部预算条 */
export interface TodayBudget {
  daily_budget: number | null
  weekly_cap: number | null
  spent_today: number
  remaining_today: number | null
  takeout_reference_price: number
}

/** 今日页临期食材 */
export interface ExpiringItem {
  inventory_id: number
  ingredient_id: number
  ingredient_name: string
  quantity: number
  unit: string
  expiry_date: string
  days_left: number
  expiring_soon: boolean
  /** 是否已经被排进今晚的菜单 */
  used_tonight: boolean
}

/** GET /api/today - 今日页一次拿全 */
export interface TodayOverview {
  date: string
  weekday: number
  weekday_label: string
  day_type: 'weekday' | 'weekend'
  generated_at: string
  ready: { has_preferences: boolean; has_menu: boolean }
  menu_id: number | null
  menu_status: MenuStatus | null
  week: {
    week_start_date: string
    status: MenuStatus
    created_at: string | null
    totals: MenuTotals
    budget: BudgetSummary
    nutrition: NutritionSummary
  } | null
  budget: TodayBudget
  meals: MealDetail[]
  tonight: TonightMeal | null
  nutrition: {
    calories: number
    protein_g: number
    target_calories: number | null
    calorie_percent: number
    meal_count: number
  } | null
  shopping: {
    to_buy_count: number
    have_count: number
    items: ShoppingItem[]
  } | null
  order: OrderSuggestion | null
  takeout: TakeoutComparison | null
  expiring: ExpiringItem[]
  timeline: TimelineEntry[]
}

/** F7 自动化状态 */
/** 用户自己的飞书机器人配置 (App Secret 只回掩码) */
export interface FeishuConfigView {
  configured: boolean
  enabled: boolean
  app_id: string
  app_secret_masked: string
  has_secret: boolean
  receive_id: string
  receive_id_type: 'open_id' | 'chat_id' | 'email' | string
  remark: string
  last_verified_at: string | null
  last_error: string | null
  /** 还差哪些必填项 (中文标签), 前端逐条提示 */
  missing_fields: string[]
  /** user = 用自己填的; deployment = 回落部署默认配置 */
  source: 'user' | 'deployment' | string
}

/** 保存飞书配置的入参 (app_secret 只写: 留空表示沿用原值) */
export interface FeishuConfigInput {
  app_id: string
  app_secret?: string | null
  receive_id: string
  receive_id_type: string
  remark?: string
  enabled?: boolean
}

export interface AutomationStatus {
  feishu: {
    configured: boolean
    /** 推送是否启用 (个人配置里可以关掉但保留参数) */
    enabled: boolean
    /** user = 用自己填的应用; deployment = 回落部署默认配置 */
    source: 'user' | 'deployment' | string
    webhook_configured: boolean
    bound: boolean
    last_push_at: string | null
    last_push_status: string | null
    last_push_title: string | null
  }
  scheduler: {
    enabled: boolean
    running: boolean
    timezone: string
    jobs: Array<{ id: string; next_run: string | null; trigger: string }>
  }
  reminders: {
    daily_menu_push: string
    evening_check: string
    expiry_check: string
    weekly_generation: string
    weekend_skipped: boolean
    note: string
  }
  notifications: Array<{
    id: number
    channel: string
    kind: string
    title: string
    detail: string | null
    status: string
    occurred_at: string
  }>
}

/** F5.1 拍照识别出的候选食材 (用户确认前不落库) */
export interface RecognitionItem {
  name: string
  quantity: number | null
  unit: string
  category: string
  confidence: number | null
  expiry_days: number | null
  ingredient_id?: number | null
  known?: boolean
}

export interface RecognitionResult {
  items: RecognitionItem[]
  model: string | null
  degraded: boolean
  used_today: number
  daily_limit: number
}
