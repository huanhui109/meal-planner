/**
 * layout_version —— 服务端下发的首页灰度版本 (R-16)
 *
 * 为什么不能只用 app 版本号:
 *   同一个 app 版本的用户可能落在 v1.1 / v1.2 两个灰度组, 只有**服务端下发**的值
 *   能把"改版是好是坏"切开。用 app 版本切片等于没有切片(而 app_version 现在 100%
 *   是 "unknown", 见数据就绪度报告)。
 *
 * 为什么放在模块级而不是 store:
 *   埋点是全站统一出口(lib/track.ts), 首页之外的页面也会打点, 走 store 会让
 *   非首页的调用方为了拿一个字符串去订阅整个决策 store。
 *
 * 读取口径: 服务端字段没就绪前一律可空 —— 拿到就用服务端的, 拿不到就退回默认值,
 * 绝不拿本地猜的值冒充灰度归属(那会让灰度结论直接失效)。
 */
/** 服务端未下发时的兜底: 与首页当前落地的布局一致 */
const DEFAULT_LAYOUT_VERSION = 'v1.2'

let current: string | null = DEFAULT_LAYOUT_VERSION

/** 当前灰度版本。拿不到时为 null, 埋点里就是 null —— 不猜 */
export function getLayoutVersion(): string | null {
  return current
}

/**
 * 用服务端下发的值覆盖。
 * 空值/非法值一律忽略: 服务端临时抽风不该把整站事件的灰度字段打成 undefined。
 */
export function applyServerLayoutVersion(value: unknown): void {
  if (typeof value !== 'string') return
  const v = value.trim()
  if (!v) return
  current = v
}

/** 测试用: 用例之间互不污染 */
export function resetLayoutVersionForTest(): void {
  current = DEFAULT_LAYOUT_VERSION
}
