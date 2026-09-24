/**
 * 首页情境判定的断言 —— V1.2.0 四条验收里能被纯函数覆盖的两条:
 *   深夜 23:40 不渲染预算条 / 营养块
 *   周末 周六 17:00 状态行显示「晚餐」且出现「再来一个」
 * 剩下两条(换一个上报 reject、结果卡不出现分钟数)在 decide-store.test.ts 与
 * home-result-card.test.ts 里。
 */
import { describe, expect, it } from 'vitest'
import { MEAL_SLOT_LABELS, resolveMealSlot } from '@shared/decide'
import {
  cookEffortLabel,
  contextBucket,
  isLateNight,
  isWeekendAnotherDishWindow,
  isWeekendMoment,
  shouldShowBudgetStrip,
  statusLine,
  stubbornAfter,
} from '@shared/decide-context'

/** 造一个本地时区的指定时刻: 直接 new Date(y, m, d, h, min) */
const at = (y: number, m: number, d: number, h: number, min: number) =>
  new Date(y, m - 1, d, h, min)

// 2026-09-23 是周三; 2026-09-26 是周六; 2026-09-21 是周一; 2026-09-25 是周五
const WED_2340 = at(2026, 9, 23, 23, 40)
const SAT_1700 = at(2026, 9, 26, 17, 0)
const MON_1900 = at(2026, 9, 21, 19, 0)
const FRI_1759 = at(2026, 9, 25, 17, 59)
const FRI_1800 = at(2026, 9, 25, 18, 0)

const statusOf = (date: Date, fridgeCount: number | null) =>
  statusLine({ date, fridgeCount, mealSlotLabel: (slot) => MEAL_SLOT_LABELS[slot] ?? '' })

describe('深夜情境', () => {
  /**
   * 边界钉的是"与 resolveMealSlot 同口径", 不是某个具体小时数:
   * 深夜边界曾经被抄成三份(config/default.yaml、shared/decide.ts、decide-context.ts),
   * 症状是"22:30 联网走夜宵、断网走晚餐"。现在这里只有一个真源。
   */
  it('深夜判定与 resolveMealSlot 完全同口径', () => {
    // 22:30 / 04:30 是"联网断网不一致"那次事故实际发生过的两个时刻
    expect(resolveMealSlot(at(2026, 9, 23, 22, 30))).toBe('late_night')
    expect(isLateNight(at(2026, 9, 23, 22, 30))).toBe(true)
    expect(resolveMealSlot(at(2026, 9, 23, 4, 30))).toBe('late_night')
    expect(isLateNight(at(2026, 9, 23, 4, 30))).toBe(true)
    // 边界两侧不能漂: 21:59 不是深夜, 05:00 也不是
    expect(resolveMealSlot(at(2026, 9, 23, 21, 59))).toBe('dinner')
    expect(isLateNight(at(2026, 9, 23, 21, 59))).toBe(false)
    expect(resolveMealSlot(at(2026, 9, 23, 5, 0))).toBe('breakfast')
    expect(isLateNight(at(2026, 9, 23, 5, 0))).toBe(false)
  })

  /**
   * 全 24 小时逐小时对拍: 只钉几个"事故时刻"不够 —— 上次漂移就是从
   * 21:59/22:00 这种边界漏出来的。这里把一天 1440 分钟全跑一遍, 任何一处
   * 两边不一致都会红出来, 不用靠人记得去验证 22:30。
   */
  it('全天 1440 分钟: isLateNight 与 resolveMealSlot 判定恒等', () => {
    for (let minute = 0; minute < 1440; minute += 1) {
      const date = at(2026, 9, 23, 0, 0)
      date.setMinutes(minute)
      const bySlot = resolveMealSlot(date) === 'late_night'
      expect(isLateNight(date), `${date.getHours()}:${date.getMinutes()} 两边不一致`).toBe(bySlot)
    }
  })

  it('23:40 属于深夜, 预算条与营养块不渲染', () => {
    expect(isLateNight(WED_2340)).toBe(true)
    expect(shouldShowBudgetStrip(WED_2340)).toBe(false)
  })

  it('深夜的倔强阈值是 2 次, 不是一刀切的 3 次', () => {
    expect(contextBucket(WED_2340)).toBe('late_night')
    expect(stubbornAfter(WED_2340)).toBe(2)
  })

  it('19:20 不是深夜, 预算条照常折叠展示', () => {
    expect(shouldShowBudgetStrip(MON_1900)).toBe(true)
  })
})

describe('周末情境', () => {
  it('周六 17:00 状态行显示「晚餐」', () => {
    expect(resolveMealSlot(SAT_1700)).toBe('dinner')
    expect(statusOf(SAT_1700, 6)).toBe('17:00 · 晚餐 · 家里有 6 样')
  })

  it('周六 17:00 出现「再来一个」(周末配菜, 不是换掉)', () => {
    expect(isWeekendAnotherDishWindow(SAT_1700)).toBe(true)
  })

  it('周末的倔强阈值放宽到 5 次 —— 她不是在纠结, 是在配一桌菜', () => {
    expect(contextBucket(SAT_1700)).toBe('weekend')
    expect(stubbornAfter(SAT_1700)).toBe(5)
  })

  it('工作日 19:00 不出现「再来一个」, 阈值保持 3 次', () => {
    expect(isWeekendAnotherDishWindow(MON_1900)).toBe(false)
    expect(stubbornAfter(MON_1900)).toBe(3)
  })

  it('周六凌晨 1 点算深夜不算周末配菜 —— 深夜优先', () => {
    const satLate = at(2026, 9, 26, 1, 0)
    expect(contextBucket(satLate)).toBe('late_night')
    expect(isWeekendAnotherDishWindow(satLate)).toBe(false)
  })
})

describe('周五晚上算周末档', () => {
  it('周五 17:59 还是工作日, 阈值 3 次', () => {
    expect(isWeekendMoment(FRI_1759)).toBe(false)
    expect(contextBucket(FRI_1759)).toBe('weekday')
    expect(stubbornAfter(FRI_1759)).toBe(3)
    expect(isWeekendAnotherDishWindow(FRI_1759)).toBe(false)
  })

  it('周五 18:00 起进入周末档, 阈值 5 次', () => {
    expect(isWeekendMoment(FRI_1800)).toBe(true)
    expect(contextBucket(FRI_1800)).toBe('weekend')
    expect(stubbornAfter(FRI_1800)).toBe(5)
  })

  it('周五 19:00 也能「再来一个」(她是在配一桌菜)', () => {
    expect(isWeekendAnotherDishWindow(at(2026, 9, 25, 19, 0))).toBe(true)
  })

  it('周五深夜仍归深夜档 —— 深夜优先于周末', () => {
    const friLate = at(2026, 9, 25, 23, 40)
    expect(contextBucket(friLate)).toBe('late_night')
    expect(stubbornAfter(friLate)).toBe(2)
  })
})

describe('出餐档位词', () => {
  it('不给精确分钟数, 只给档位', () => {
    expect(cookEffortLabel(10)).toBe('快手')
    // 22 是"荤菜"的品类默认值(119 道菜都是它), 落在"还行"而不是假装精确
    expect(cookEffortLabel(22)).toBe('还行')
    expect(cookEffortLabel(45)).toBe('要小火慢炖')
  })
})

describe('状态行', () => {
  it('深夜显示夜宵, 没录冰箱时不硬凑"家里有 0 样"', () => {
    expect(statusOf(WED_2340, null)).toBe('23:40 · 夜宵')
    expect(statusOf(WED_2340, 0)).toBe('23:40 · 夜宵')
  })
})
