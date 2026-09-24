/**
 * layout_version —— 服务端下发的首页灰度版本 (R-16) 小程序端
 *
 * 与 H5 的 lib/layout-version.ts 是同一份契约, 读取口径必须一致:
 *   服务端 /decide 下发就记它下发的; 没下发(或未配置返回 null)就用本地默认值。
 *
 * ⚠ 为什么"服务端返回 null"不能当成"不在任何组"来记:
 *   NULL 在 SQL 里既不是 v1.1 也不是 v1.2, `GROUP BY layout_version` 时这批行
 *   会单独成一组甚至被 WHERE 条件滤掉 —— 整批样本静默从切片里消失, 灰度结论失效。
 *   服务端那侧的 null 是"我不知道", 前端这侧该做的是退回自己的默认值, 不是照抄 null。
 *
 * 为什么不用 app 版本切片: 同一个 app 版本的用户可能落在两个灰度组,
 *   只有服务端下发的值能把"改版是好是坏"切开。
 *
 * 与服务端的分工: 服务端 current_layout_version() 未配置时返回 null(刻意的),
 * 前端拿到 null **不要**用它覆盖自己的默认值 —— 否则所有事件的灰度字段会静默变空,
 * 而"空"在 SQL 里既不是 v1.1 也不是 v1.2, 整批样本会从切片里消失。
 */
const DEFAULT_LAYOUT_VERSION = 'v1.2'

let current: string | null = DEFAULT_LAYOUT_VERSION

/** 当前灰度版本。服务端没下发时是本地默认值 'v1.2' */
export function getLayoutVersion(): string | null {
  return current
}

/**
 * 用服务端下发的值覆盖 (/decide 响应的 layout_version)。
 * null / 空串 / 非法值一律忽略: 服务端"不知道分在哪组"时前端保持默认值,
 * 服务端临时抽风也不该把整站事件的灰度字段打成 undefined。
 */
export function applyServerLayoutVersion(value: unknown): void {
  if (typeof value !== 'string') return
  const v = value.trim()
  if (!v) return
  current = v
}
