/**
 * 共享层数字/文案规范的回归测试
 *
 * 这些规则直接决定界面上数字长什么样, 两端共用, 所以放在这里锁住:
 *   * 金额永远 1 位小数且不出现多余小数 (¥18.5 / ¥310, 不是 ¥18.50 / ¥18.499999)
 *   * 热量/分钟/比例取整
 *   * 数量最多 2 位小数并去尾随 0
 *   * 日期是中文月日, 且不因 UTC 偏移串日期
 */
import { describe, expect, it } from 'vitest'
import {
  addDays,
  currentWeekStart,
  daysBetween,
  formatAmount,
  formatDateRange,
  formatExpiry,
  formatKcal,
  formatMinutes,
  formatMoney,
  formatMonthDay,
  formatPercent,
  formatProgress,
  formatQuantity,
  formatRemaining,
  todayIso,
  toIsoDate,
  trimNumber,
  weekEnd,
} from '@shared/format'

describe('formatMoney', () => {
  it('保留 1 位小数', () => {
    expect(formatMoney(18.5)).toBe('¥18.5')
    expect(formatMoney(0.05)).toBe('¥0.1')
  })

  it('整数不带小数点', () => {
    expect(formatMoney(310)).toBe('¥310')
    expect(formatMoney(0)).toBe('¥0')
  })

  it('抹掉浮点误差, 不出现长小数', () => {
    expect(formatMoney(18.499999)).toBe('¥18.5')
    expect(formatMoney(0.1 + 0.2)).toBe('¥0.3')
  })

  it('空值当 0 处理', () => {
    expect(formatMoney(null)).toBe('¥0')
    expect(formatMoney(undefined)).toBe('¥0')
    expect(formatMoney(undefined, false)).toBe('0')
  })

  it('可以不带货币符号', () => {
    expect(formatMoney(18.5, false)).toBe('18.5')
  })
})

describe('formatQuantity / formatAmount', () => {
  it('去尾随 0', () => {
    expect(formatQuantity(2)).toBe('2')
    expect(formatQuantity(1.5)).toBe('1.5')
    expect(formatQuantity(0.25)).toBe('0.25')
    expect(formatQuantity(2.0)).toBe('2')
  })

  it('单位跟在数字后', () => {
    expect(formatAmount(200, 'g')).toBe('200g')
    expect(formatAmount(2, '个')).toBe('2个')
  })

  it('数量为空表示适量', () => {
    expect(formatAmount(null, 'g')).toBe('适量')
    expect(formatAmount(undefined, '个')).toBe('适量')
  })
})

describe('formatKcal / formatMinutes / formatPercent', () => {
  it('一律取整', () => {
    expect(formatKcal(519.6)).toBe('520 kcal')
    expect(formatMinutes(34.5)).toBe('35 分钟')
    expect(formatPercent(29.6)).toBe('30%')
  })

  it('空值不显示假数字 (热量/分钟)', () => {
    expect(formatKcal(null)).toBe('')
    expect(formatMinutes(undefined)).toBe('')
  })

  it('进度用 done/total 单位', () => {
    expect(formatProgress(12, 14)).toBe('12/14 餐')
    expect(formatProgress(0, 14, '道')).toBe('0/14 道')
  })
})

describe('日期', () => {
  it('中文月日不补 0', () => {
    expect(formatMonthDay('2026-08-18')).toBe('8月18日')
    expect(formatMonthDay('2026-12-01')).toBe('12月1日')
    expect(formatMonthDay(null)).toBe('')
  })

  it('区间用短横线连接', () => {
    expect(formatDateRange('2026-08-18', '2026-08-24')).toBe('8月18日 – 8月24日')
  })

  it('toIsoDate 用本地时区, 不走 UTC (否则晚上会串到前一天)', () => {
    expect(toIsoDate(new Date(2026, 7, 18, 23, 30))).toBe('2026-08-18')
    expect(toIsoDate(new Date(2026, 0, 1, 0, 5))).toBe('2026-01-01')
  })

  it('todayIso 跟随传入的基准时间', () => {
    expect(todayIso(new Date(2026, 8, 10))).toBe('2026-09-10')
  })

  it('一周从周一开始', () => {
    // 2026-09-10 是周四
    expect(currentWeekStart(new Date(2026, 8, 10))).toBe('2026-09-07')
    // 周日要算进上一周
    expect(currentWeekStart(new Date(2026, 8, 13))).toBe('2026-09-07')
    expect(currentWeekStart(new Date(2026, 8, 14))).toBe('2026-09-14')
  })

  it('加减天数与差值', () => {
    expect(addDays('2026-08-31', 1)).toBe('2026-09-01')
    expect(daysBetween('2026-08-18', '2026-08-24')).toBe(6)
    expect(weekEnd('2026-08-18')).toBe('2026-08-24')
  })

  it('保质期文案口语化', () => {
    expect(formatExpiry(-2)).toBe('已过期 2 天')
    expect(formatExpiry(0)).toBe('今天到期')
    expect(formatExpiry(1)).toBe('明天到期')
    expect(formatExpiry(3)).toBe('还有 3 天')
    expect(formatExpiry(null)).toBe('')
  })

  it('剩余天数更短, 适合卡片角标', () => {
    expect(formatRemaining(-1)).toBe('过期 1 天')
    expect(formatRemaining(0)).toBe('今天用完')
    expect(formatRemaining(5)).toBe('剩 5 天')
    expect(formatRemaining(undefined)).toBe('')
  })
})

describe('trimNumber', () => {
  it('保留指定小数位并去掉尾随 0', () => {
    expect(trimNumber(1.005, 2)).toBe('1')
    expect(trimNumber(1.239, 2)).toBe('1.24')
    expect(trimNumber(null)).toBe('0')
    expect(trimNumber(Number.NaN)).toBe('0')
  })
})
