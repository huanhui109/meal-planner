/**
 * 业务接口 - 与 H5 的 frontend/src/api/* 一一对应, 路径常量取自共享层
 */
import { ENDPOINTS } from '@shared/endpoints'
import type {
  AuthProviders,
  AutomationStatus,
  BuildInfo,
  ConsumeResult,
  CurrentUser,
  EventBatch,
  EventBatchAck,
  EventBatchItem,
  FridgeRebuildPayload,
  GenerateAccepted,
  GenerationMode,
  GenerationTask,
  InventoryItem,
  MenuDetail,
  OrderSuggestion,
  RecognitionResult,
  ShoppingList,
  SubscribeStatus,
  SubscribeTemplate,
  TodayOverview,
  UserPreferenceSummary,
} from '@shared/types'

import Taro from '@tarojs/taro'

import { BASE_URL, http } from './request'
import { getAccessToken, type TokenBundle } from './session'

// ---------- 认证 ----------

export const getAuthProviders = () =>
  http.get<AuthProviders>(ENDPOINTS.authProviders, { skipAuthRedirect: true })

export const fetchCurrentUser = () => http.get<CurrentUser>(ENDPOINTS.authMe)

export const logout = () => http.post<null>(ENDPOINTS.authLogout)

/** 微信一键登录: code 来自 Taro.login() */
export const wechatMiniLogin = (code: string) =>
  http.post<TokenBundle>(ENDPOINTS.wechatMiniLogin, { code }, { skipAuthRedirect: true })

/** 本地开发登录 (仅当后端 APP__AUTH__DEV_LOGIN=true), 开发期用它打通全链路 */
export const devLogin = (name: string) =>
  http.post<TokenBundle & CurrentUser>(ENDPOINTS.devLogin, { name }, { skipAuthRedirect: true })

// ---------- 偏好 ----------

export const getPreferenceSummary = () =>
  http.get<UserPreferenceSummary>(ENDPOINTS.preferenceSummary)

export const saveHousehold = (data: Record<string, unknown>) =>
  http.put<unknown>(ENDPOINTS.household, data)

export const saveDiet = (data: Record<string, unknown>) => http.put<unknown>(ENDPOINTS.diet, data)

export const saveAllergy = (data: Record<string, unknown>) =>
  http.put<unknown>(ENDPOINTS.allergy, data)

export const saveHealthGoal = (data: Record<string, unknown>) =>
  http.put<unknown>(ENDPOINTS.healthGoal, data)

export const saveBudget = (data: Record<string, unknown>) => http.put<unknown>(ENDPOINTS.budget, data)

// ---------- 菜单 ----------

export const generateMenu = (weekStart: string, force = false, mode: GenerationMode = 'auto') =>
  http.post<GenerateAccepted>(ENDPOINTS.generateMenu, { week_start: weekStart, force, mode })

export const getGenerationTask = (taskId: number) =>
  http.get<GenerationTask>(ENDPOINTS.generationTask(taskId))

export const getCurrentMenu = () => http.get<MenuDetail | null>(ENDPOINTS.currentMenu)

/** 历史菜单 (audit T3.3) - 回溯 weeks 周 (默认 4, 上限 12) */
export const getMenuHistory = (weeks = 4) =>
  http.get<{
    weeks: number
    total: number
    items: Array<{
      id: number
      week_start_date: string | null
      status: string
      is_confirmed: boolean
      totals: Record<string, unknown>
    }>
  }>(`${ENDPOINTS.menuHistory}?weeks=${weeks}`)

export const getMenu = (menuId: number) => http.get<MenuDetail>(ENDPOINTS.menu(menuId))

export const confirmMenu = (menuId: number) =>
  http.post<{ menu_id: number; status: string }>(ENDPOINTS.confirmMenu(menuId))

export const getShoppingList = (menuId: number) =>
  http.get<ShoppingList>(ENDPOINTS.shoppingList(menuId))

/** 按冰箱现有食材重排本周: 同步完成, 不调 LLM 也不消耗生成额度 */
export const rebuildFromFridge = (weekStart: string) =>
  http.post<FridgeRebuildPayload>(ENDPOINTS.fridgeRebuild, { week_start: weekStart })

export const replaceMenuItem = (
  menuId: number,
  itemId: number,
  body: {
    /** 留空 body 走自动模式: 本地菜谱库优先, 挑不到再 AI 生成 */
    recipe_id?: number
    recipe_name?: string
    calories?: number
    cook_minutes?: number
    steps?: string
  } = {},
) => http.put<MenuDetail>(ENDPOINTS.replaceMenuItem(menuId, itemId), body)

export const lockMenuItem = (menuId: number, itemId: number) =>
  http.put<{ item_id: number; is_locked: boolean }>(ENDPOINTS.lockMenuItem(menuId, itemId))

export const unlockMenuItem = (menuId: number, itemId: number) =>
  http.put<{ item_id: number; is_locked: boolean }>(ENDPOINTS.unlockMenuItem(menuId, itemId))

/** 标记已做: 后端会按菜谱扣减冰箱库存 */
export const markItemCooked = (menuId: number, itemId: number) =>
  http.put<ConsumeResult>(ENDPOINTS.cookedMenuItem(menuId, itemId))

/** 今日饭决「做完了」: 按结果菜谱扣减冰箱库存 (2.7.0) */
export const cookDecision = (decisionId: number) =>
  http.post<{
    decision_id: number
    already_cooked: boolean
    no_recipe?: boolean
    consumed: Array<{ ingredient_name: string; quantity: number; unit: string }>
    missing: Array<{ ingredient_name: string; quantity: number; unit: string }>
  }>(ENDPOINTS.decideCook(decisionId))

/** 撤销「标记已做」: 库存还原 + 删除消耗流水 */
export const undoMarkItemCooked = (menuId: number, itemId: number) =>
  http.del<{ item_id: number; restored: unknown[] }>(ENDPOINTS.undoCookedMenuItem(menuId, itemId))

/** 补单建议 (采购页 / 今日页共用) */
export const getOrderSuggestion = (menuId: number) =>
  http.get<OrderSuggestion>(ENDPOINTS.orderSuggestion(menuId))

// ---------- 今日 ----------

export const getToday = () => http.get<TodayOverview>(ENDPOINTS.today)

/** 记住用户在卡片上改的外卖参考价 */
export const rememberTakeoutPrice = (price: number) =>
  http.post<{ takeout_reference_price: number }>(ENDPOINTS.takeoutPrice, { price })

// ---------- 自动化 ----------

export const getAutomationStatus = () =>
  http.get<AutomationStatus>(ENDPOINTS.automationStatus)

// ---------- 库存 ----------

/** 拍照识别: 只返回候选清单, 确认后逐条 addInventory */
export const recognizeInventory = (filePath: string) =>
  new Promise<RecognitionResult>((resolve, reject) => {
    const token = getAccessToken()
    Taro.uploadFile({
      url: `${BASE_URL}${ENDPOINTS.inventoryRecognize}`,
      filePath,
      name: 'file',
      header: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 60000,
      success: (res) => {
        try {
          const envelope = JSON.parse(res.data) as {
            data?: RecognitionResult
            detail?: string
            message?: string
          }
          if (res.statusCode >= 400) {
            reject(new Error(envelope.detail || envelope.message || '识别失败'))
            return
          }
          resolve(envelope.data as RecognitionResult)
        } catch {
          reject(new Error('识别结果解析失败'))
        }
      },
      fail: () => reject(new Error('上传失败, 请检查网络')),
    })
  })

// ---------- 库存 ----------

/** 后端 GET /inventory 返回 { total, expiring_count, items },
 *  与 H5 的 listInventory 契约一致, 这里只取 items 数组给页面用 */
export const listInventory = () =>
  http.get<{ total: number; expiring_count: number; items: InventoryItem[] }>(ENDPOINTS.inventory)

export const addInventory = (data: Record<string, unknown>) =>
  http.post<InventoryItem>(ENDPOINTS.inventory, data)

export const deleteInventory = (itemId: number) =>
  http.del<null>(ENDPOINTS.inventoryItem(itemId))

/** 按食材名模糊搜索库存 (GET /inventory?q=, 2.7.0) */
export const searchInventory = (q: string) =>
  http.get<{ total: number; expiring_count: number; items: InventoryItem[] }>(
    `${ENDPOINTS.inventory}?q=${encodeURIComponent(q)}`,
  )

/** 批量入库 (快速补常备食材, 2.7.0) */
export const bulkAddInventory = (
  items: Array<{ ingredient_name: string; quantity: number; unit: string }>,
) => http.post<{ added: InventoryItem[] }>(ENDPOINTS.inventoryBulk, { items })

/** 改库存项的数量 / 保质期 (PUT /inventory/{id}, 2.7.0) */
export const updateInventoryItem = (
  itemId: number,
  body: { quantity?: number; expiry_date?: string | null },
) => http.put<InventoryItem>(ENDPOINTS.inventoryItem(itemId), body)

// ---------- 反馈 ----------

export type FeedbackCategory = 'bug' | 'suggestion' | 'recipe' | 'other'

export interface FeedbackAck {
  id: number
  category: string
  status: string
  created_at: string | null
}

const CATEGORY_VALUES: FeedbackCategory[] = ['bug', 'suggestion', 'recipe', 'other']

const sanitizeCategory = (value: string): FeedbackCategory =>
  CATEGORY_VALUES.includes(value as FeedbackCategory) ? (value as FeedbackCategory) : 'other'

/** 提交反馈 (匿名也允许: getCurrentUser_optional 后端处理) */
export const submitFeedback = (data: {
  category: FeedbackCategory
  content: string
  contact?: string
  device_info?: string
}) =>
  http.post<FeedbackAck>(ENDPOINTS.feedback, {
    category: sanitizeCategory(data.category),
    content: data.content.trim(),
    contact: data.contact?.trim() || undefined,
    device_info: data.device_info,
  })

/** 我的反馈历史 (匿名返回空列表) */
export const listMyFeedback = () =>
  http.get<{ total: number; items: Array<{ id: number; category: string; content: string; status: string; created_at: string | null }> }>(
    ENDPOINTS.feedbackMine,
  )

// ---------- 版本检测 ----------

/** 启动期拉版本元信息: 决定是否强制升级 / 弹升级 toast */
export const getBuildInfo = () =>
  http.get<BuildInfo>(ENDPOINTS.buildInfo, { skipAuthRedirect: true })

// ---------- 埋点 ----------

/** 批量上报: 单批最多 50 条 */
export const reportEvents = (events: Array<{
  event_name: string
  ts: number
  properties?: Record<string, unknown> | null
  app_version?: string | null
  platform?: string | null
}>) =>
  http.post<EventBatchAck>(
    ENDPOINTS.events,
    { events },
    { skipAuthRedirect: true },
  )

// ---------- 订阅消息 ----------

export const getSubscribeTemplates = () =>
  http.get<{ items: SubscribeTemplate[] }>(ENDPOINTS.subscribeTemplates)

export const grantSubscribe = (data: {
  template_id: string
  grant: boolean
  accepted?: 'accept' | 'deny' | 'ban' | null
}) =>
  http.post<null>(ENDPOINTS.subscribeGrant, data)

export const getSubscribeStatus = (templateId: string) =>
  http.get<SubscribeStatus>(ENDPOINTS.subscribeStatus(templateId))

// ---------- V3.0 实价查询 ----------

/** 按食材名搜索商品 (audit T4.1)
 * 当前 (Stub) 返回空数组 + v3_status 字段, 真实数据待 V3.x 接入
 */
export const searchProducts = (ingredient: string) =>
  http.get<{
    ingredient: string
    total: number
    items: Array<{
      id: number
      name: string
      category: string | null
      price: number
      unit: string | null
      in_stock: boolean
      price_changed: boolean
      platform: string
    }>
    v3_status?: string
  }>(`${ENDPOINTS.productSearch}?ingredient=${encodeURIComponent(ingredient)}`)

// ---------- 邀请裂变 ----------

export const getInviteCode = () =>
  http.get<{
    code: string
    share_path: string
    invite_count: number
    reward_granted: number
  }>(ENDPOINTS.inviteCode)

export const redeemInviteCode = (code: string) =>
  http.post<{ ok: boolean; message: string; reward: number | null }>(
    ENDPOINTS.inviteRedeem,
    { code },
  )
