/**
 * 运行期配置 (小程序)
 *
 * API 基址由 Taro 的 defineConstants 注入 (config/dev.ts / config/prod.ts),
 * 这里只做一次兜底与派生, 页面不用再各自处理 undefined。
 */
export const API_BASE = typeof API_BASE_URL === 'string' ? API_BASE_URL : 'http://127.0.0.1:8000/api'

/** 展示给用户看的"当前部署域名"(我的页底部的数据存放说明用) */
export const BRAND_HOST = (() => {
  const match = /^https?:\/\/([^/]+)/.exec(API_BASE)
  return match?.[1] ?? '本地开发环境'
})()
