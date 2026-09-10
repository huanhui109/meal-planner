/**
 * 数字与文案格式化 - H5 与小程序共用
 *
 * 规范 (见 docs/design-system.md):
 *   * 金额永远 1 位小数, 整数不带小数点: ¥18.5 / ¥310 (不出现 ¥18.50 / ¥18.499999)
 *   * 热量、分钟、比例一律取整
 *   * 数量最多 2 位小数, 且去掉尾随 0: 2 / 1.5 / 0.25
 *   * 日期用中文月日: 8月18日; 区间用 8月18日 – 8月24日
 *   * 单位跟在数字后面, 由界面用小号灰字呈现
 */

const WEEK_MS = 7 * 24 * 60 * 60 * 1000

/** 去掉浮点误差与尾随 0, 最多保留 maxDigits 位小数 */
export function trimNumber(value: number | null | undefined, maxDigits = 2): string {
  if (value == null || Number.isNaN(value)) return '0'
  const rounded = Number(value.toFixed(maxDigits))
  return String(rounded)
}

/** 金额: ¥18.5 / ¥310 / ¥0 */
export function formatMoney(value: number | null | undefined, withSymbol = true): string {
  if (value == null || Number.isNaN(value)) return withSymbol ? '¥0' : '0'
  const rounded = Math.round(value * 10) / 10
  return `${withSymbol ? '¥' : ''}${rounded}`
}

/** 数量: 2 / 1.5 / 0.25 */
export function formatQuantity(value: number | null | undefined): string {
  return trimNumber(value, 2)
}

/** 数量 + 单位: 2个 / 200g / 适量 (数量为空表示"适量") */
export function formatAmount(quantity: number | null | undefined, unit = ''): string {
  if (quantity == null) return '适量'
  return `${formatQuantity(quantity)}${unit}`
}

/** 热量: 520 kcal */
export function formatKcal(value: number | null | undefined): string {
  if (value == null) return ''
  return `${Math.round(value)} kcal`
}

/** 时长: 35 分钟 */
export function formatMinutes(value: number | null | undefined): string {
  if (value == null) return ''
  return `${Math.round(value)} 分钟`
}

/** 比例: 30% */
export function formatPercent(value: number | null | undefined): string {
  if (value == null) return '0%'
  return `${Math.round(value)}%`
}

/** 进度: 12/14 餐 */
export function formatProgress(done: number, total: number, unit = '餐'): string {
  return `${done}/${total} ${unit}`
}

/** 8月18日 */
export function formatMonthDay(isoDate: string | null | undefined): string {
  if (!isoDate) return ''
  const [, month, day] = isoDate.split('-')
  if (!month || !day) return isoDate
  return `${Number(month)}月${Number(day)}日`
}

/** 8月18日 – 8月24日 */
export function formatDateRange(startIso: string, endIso: string): string {
  return `${formatMonthDay(startIso)} – ${formatMonthDay(endIso)}`
}

/** 保质期: 明天到期 / 还有 3 天 / 已过期 2 天 / 今天到期 */
export function formatExpiry(daysLeft: number | null | undefined): string {
  if (daysLeft == null) return ''
  if (daysLeft < 0) return `已过期 ${-daysLeft} 天`
  if (daysLeft === 0) return '今天到期'
  if (daysLeft === 1) return '明天到期'
  return `还有 ${daysLeft} 天`
}

/** 剩余天数口语化: 剩 3 天 / 今天用完 */
export function formatRemaining(daysLeft: number | null | undefined): string {
  if (daysLeft == null) return ''
  if (daysLeft < 0) return `过期 ${-daysLeft} 天`
  if (daysLeft === 0) return '今天用完'
  return `剩 ${daysLeft} 天`
}

/** 本地时区的 YYYY-MM-DD (不用 toISOString, 避免 UTC 偏移串日期) */
export function toIsoDate(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/** 今天 */
export function todayIso(base: Date = new Date()): string {
  return toIsoDate(base)
}

/** 本周周一 (周一为一周第一天, 与菜单的自然周一致) */
export function currentWeekStart(base: Date = new Date()): string {
  const date = new Date(base)
  const weekday = (date.getDay() + 6) % 7
  date.setDate(date.getDate() - weekday)
  return toIsoDate(date)
}

/** ISO 日期加减天数 */
export function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00`)
  date.setDate(date.getDate() + days)
  return toIsoDate(date)
}

/** 两个 ISO 日期相差的天数 */
export function daysBetween(fromIso: string, toIso: string): number {
  const from = new Date(`${fromIso}T00:00:00`).getTime()
  const to = new Date(`${toIso}T00:00:00`).getTime()
  return Math.round((to - from) / (24 * 60 * 60 * 1000))
}

/** 一周的结束日期 (周一 + 6 天) */
export function weekEnd(weekStartIso: string): string {
  return addDays(weekStartIso, 6)
}

export { WEEK_MS }
