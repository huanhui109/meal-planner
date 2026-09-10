/**
 * 业务接口 - 与 H5 的 frontend/src/api/* 一一对应, 路径常量取自共享层
 */
import { ENDPOINTS } from '@shared/endpoints'
import type {
  AuthProviders,
  AutomationStatus,
  ConsumeResult,
  CurrentUser,
  GenerateAccepted,
  GenerationTask,
  InventoryItem,
  MenuDetail,
  OrderSuggestion,
  RecognitionResult,
  ShoppingList,
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

export const generateMenu = (weekStart: string, force = false) =>
  http.post<GenerateAccepted>(ENDPOINTS.generateMenu, { week_start: weekStart, force })

export const getGenerationTask = (taskId: number) =>
  http.get<GenerationTask>(ENDPOINTS.generationTask(taskId))

export const getCurrentMenu = () => http.get<MenuDetail | null>(ENDPOINTS.currentMenu)

export const getMenu = (menuId: number) => http.get<MenuDetail>(ENDPOINTS.menu(menuId))

export const confirmMenu = (menuId: number) =>
  http.post<{ menu_id: number; status: string }>(ENDPOINTS.confirmMenu(menuId))

export const getShoppingList = (menuId: number) =>
  http.get<ShoppingList>(ENDPOINTS.shoppingList(menuId))

export const replaceMenuItem = (
  menuId: number,
  itemId: number,
  body: { recipe_name: string; calories?: number; cook_minutes?: number; steps?: string },
) => http.put<MenuDetail>(ENDPOINTS.replaceMenuItem(menuId, itemId), body)

export const lockMenuItem = (menuId: number, itemId: number) =>
  http.put<{ item_id: number; is_locked: boolean }>(ENDPOINTS.lockMenuItem(menuId, itemId))

export const unlockMenuItem = (menuId: number, itemId: number) =>
  http.put<{ item_id: number; is_locked: boolean }>(ENDPOINTS.unlockMenuItem(menuId, itemId))

/** 标记已做: 后端会按菜谱扣减冰箱库存 */
export const markItemCooked = (menuId: number, itemId: number) =>
  http.put<ConsumeResult>(ENDPOINTS.cookedMenuItem(menuId, itemId))

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

export const listInventory = () => http.get<InventoryItem[]>(ENDPOINTS.inventory)

export const addInventory = (data: Record<string, unknown>) =>
  http.post<InventoryItem>(ENDPOINTS.inventory, data)

export const deleteInventory = (itemId: number) =>
  http.del<null>(ENDPOINTS.inventoryItem(itemId))
