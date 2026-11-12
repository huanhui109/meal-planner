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
  /** 批量入库 (快速补常备食材, 2.7.0) */
  inventoryBulk: '/inventory/bulk',
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
  /** 今日饭决「做完了」: 按结果菜谱扣减冰箱库存 (2.7.0) */
  decideCook: (decisionId: number) => `/decide/${decisionId}/cook`,

  today: '/today',
  takeoutPrice: '/today/takeout-price',
  orderSuggestion: (menuId: number) => `/menus/${menuId}/order-suggestion`,
  automationStatus: '/automation/status',
  automationFeishu: '/automation/feishu',
  automationFeishuTest: '/automation/feishu/test',

  // 饭决 Skill / 助手连接 (既有端点, 补录单真源缺口; 取值与 backend/app/api/assistant.py 一致)
  assistantGrants: '/assistant/grants',
  assistantGrant: (id: string) => `/assistant/grants/${encodeURIComponent(id)}`,
  assistantSkillZip: '/assistant/skill.zip',
  assistantWorkBuddy: '/assistant/workbuddy',
  assistantWorkBuddyAuthorize: '/assistant/workbuddy/authorize',
  assistantModelStatus: '/assistant/model',
  /** 发起 / 轮询 / 退出本机 WorkBuddy 登录 (2.9.0) */
  assistantLogin: '/assistant/login',
  assistantLoginStatus: (id: string) => `/assistant/login/${encodeURIComponent(id)}`,
  assistantAdjustments: '/assistant/adjustments',
  /** 应用内候选菜品技能：模糊描述 → 3-5 个结构化候选 (单跳低延迟) */
  assistantCandidates: '/assistant/candidates',
  assistantAdjustmentsCurrent: '/assistant/adjustments/current',
  assistantAdjustment: (id: string) => `/assistant/adjustments/${encodeURIComponent(id)}`,
  assistantAdjustmentCancel: (id: string) => `/assistant/adjustments/${encodeURIComponent(id)}/cancel`,

  // 双向唤醒模块 (2.9.0 独立特性, 默认关闭)
  inboundBridgeEvents: '/inbound/bridge/events',
  inboundBridgeReceipts: '/inbound/bridge/receipts',
  inboundBridgeStatus: '/inbound/bridge/status',
  inboundBridgePoll: '/inbound/bridge/poll',
  inboundBridgePair: '/inbound/bridge/pair',
  inboundBridgePairRotate: (id: string) => `/inbound/bridge/pair/${encodeURIComponent(id)}/rotate`,
  inboundBridgePairItem: (id: string) => `/inbound/bridge/pair/${encodeURIComponent(id)}`,
  inboundBridgeAllowlist: '/inbound/bridge/allowlist',
  inboundBridgeAudit: '/inbound/bridge/audit',
} as const

export default ENDPOINTS
