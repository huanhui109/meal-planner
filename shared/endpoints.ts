/**
 * 接口路径常量 - H5 与小程序共用, 避免两端各写一份字符串
 *
 * 都相对于 API 前缀 (H5 走 /api 代理, 小程序走 https://<域名>/api)。
 */
export const ENDPOINTS = {
  authProviders: '/auth/providers',
  authMe: '/auth/me',
  authRefresh: '/auth/refresh',
  authLogout: '/auth/logout',
  feishuLoginUrl: '/auth/feishu/login-url',
  devLogin: '/auth/dev-login',
  wechatMiniLogin: '/auth/wechat/mini-login',

  preferenceSummary: '/preferences/summary',
  household: '/preferences/household',
  diet: '/preferences/diet',
  allergy: '/preferences/allergy',
  healthGoal: '/preferences/health-goal',
  budget: '/preferences/budget',

  generateMenu: '/menus/generate',
  /** 按冰箱现有食材重排本周 (同步完成, 不调 LLM) */
  fridgeRebuild: '/menus/fridge-rebuild',
  currentMenu: '/menus/current',
  menuHistory: '/menus/history',
  generationTask: (taskId: number) => `/menus/generation-tasks/${taskId}`,
  menu: (menuId: number) => `/menus/${menuId}`,
  confirmMenu: (menuId: number) => `/menus/${menuId}/confirm`,
  shoppingList: (menuId: number) => `/menus/${menuId}/shopping-list`,
  replaceMenuItem: (menuId: number, itemId: number) => `/menus/${menuId}/items/${itemId}/replace`,
  lockMenuItem: (menuId: number, itemId: number) => `/menus/${menuId}/items/${itemId}/lock`,
  unlockMenuItem: (menuId: number, itemId: number) => `/menus/${menuId}/items/${itemId}/unlock`,
  cookedMenuItem: (menuId: number, itemId: number) => `/menus/${menuId}/items/${itemId}/cooked`,
  undoCookedMenuItem: (menuId: number, itemId: number) => `/menus/${menuId}/items/${itemId}/cooked`,

  inventory: '/inventory',
  inventoryItem: (itemId: number) => `/inventory/${itemId}`,
  inventoryRecognize: '/inventory/recognize',

  feedback: '/feedback',
  feedbackMine: '/feedback/mine',

  buildInfo: '/build-info',

  events: '/events',

  subscribeTemplates: '/subscribe/templates',
  subscribeGrant: '/subscribe/grant',
  subscribeStatus: (templateId: string) => `/subscribe/status/${templateId}`,

  productSearch: '/products/search',

  inviteCode: '/invite/code',
  inviteRedeem: '/invite/redeem',

  // 饭决决策 (v1.0.0)
  decide: '/decide',
  decideLast: '/decide/last',
  decideProfile: '/decide/profile',
  decideRecent: '/decide/recent',
  decideFeedback: (decisionId: number) => `/decide/${decisionId}/feedback`,

  today: '/today',
  takeoutPrice: '/today/takeout-price',
  orderSuggestion: (menuId: number) => `/menus/${menuId}/order-suggestion`,
  automationStatus: '/automation/status',
  automationFeishu: '/automation/feishu',
  automationFeishuTest: '/automation/feishu/test',
} as const

export default ENDPOINTS
