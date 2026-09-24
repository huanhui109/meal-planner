/**
 * 饭决离线决策单测 (需求 5 / 6 / 7 / 9 / 10)
 *
 * 这些断言必须和 backend/tests/unit/test_decide_rules.py 一一对应 ——
 * 断网时用户走的是这份代码, 联网时走 Python。两端行为不一致是最难排查的一类 bug。
 */
import { describe, expect, it } from 'vitest'
import {
  buildReason,
  clipSteps,
  decideOffline,
  normalizeDishName,
  resolveMealSlot,
  type DecideHistoryItem,
  type OfflineProfile,
} from '../shared/decide'
import { LOCAL_DISHES } from '../shared/local-pool.generated'
import { ONBOARDING_QUESTIONS, toPreferencePayload } from '../shared/onboarding'

const PROFILE: OfflineProfile = { cuisines: ['家常'], spiceLevel: 2, avoid: [], cookCap: 60 }

function hist(name: string, daysAgo = 1): DecideHistoryItem[] {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  const date = `${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, '0')}-${`${d.getDate()}`.padStart(2, '0')}`
  return [{ name, date }]
}

describe('菜名归一化', () => {
  it('番茄炒蛋 与 西红柿炒鸡蛋 判成同一道菜', () => {
    expect(normalizeDishName('西红柿 炒鸡蛋')).toBe(normalizeDishName('番茄炒蛋'))
  })
  it('去标点符号', () => {
    expect(normalizeDishName('番茄（炒）蛋')).toBe(normalizeDishName('番茄炒蛋'))
  })
})

describe('需求 5: 近 7 天不重复', () => {
  it('昨天吃过的菜不会再出现', () => {
    const eaten = LOCAL_DISHES[0].n
    for (let i = 0; i < 30; i += 1) {
      const out = decideOffline({ profile: PROFILE, history: hist(eaten) }, new Date())
      expect(out).not.toBeNull()
      expect(normalizeDishName(out!.dish.n)).not.toBe(normalizeDishName(eaten))
    }
  })

  it('8 天前吃过的菜可以再出现(不在窗口内)', () => {
    const seen = new Set<string>()
    for (let i = 0; i < 60; i += 1) {
      const out = decideOffline({ profile: PROFILE, history: hist(LOCAL_DISHES[0].n, 8) })
      if (out) seen.add(out.dish.n)
    }
    // 不能断言"一定会出现"(有随机), 但至少要能选到它之外的菜 —— 候选池没被误杀
    expect(seen.size).toBeGreaterThan(3)
  })

  it('手动排除的菜不再出现', () => {
    const banned = LOCAL_DISHES[1].n
    const out = decideOffline({ profile: PROFILE, history: [], exclude: [banned] })
    expect(out).not.toBeNull()
    expect(out!.dish.n).not.toBe(banned)
  })
})

describe('需求 5: 同品类打散', () => {
  it('最近 3 餐都是汤羹时, 汤羹被明显压制', () => {
    const soups = LOCAL_DISHES.filter((d) => d.ca === '汤羹').slice(0, 3)
    const history: DecideHistoryItem[] = soups.map((d) => ({
      name: d.n,
      category: d.ca,
      cuisine: d.cu,
      main: d.mi,
      date: new Date().toISOString().slice(0, 10),
    }))
    const counts: Record<string, number> = {}
    for (let i = 0; i < 80; i += 1) {
      const out = decideOffline({ profile: PROFILE, history })
      if (out) counts[out.dish.ca] = (counts[out.dish.ca] || 0) + 1
    }
    const soupPicks = counts['汤羹'] || 0
    // 允许偶尔出现(软随机), 但不该是主流
    expect(soupPicks).toBeLessThan(40)
  })
})

describe('需求 9: 深夜只给轻食或主食/面食', () => {
  // 旧口径是「light 且 <=20 分钟」, 池子里主食/面食/汤羹一道都没有, "想吃碗面"无解。
  // 现在深夜额外放行主食/面食类快手菜 (见 LATE_NIGHT_EXTRA_CATEGORIES 处的注释),
  // 白名单只在深夜生效, 不碰 light 标记 —— light 白天还要服务"来点清淡的"。
  const LATE_OK = (d: (typeof LOCAL_DISHES)[number]) =>
    d.lt || ['主食', '面食'].includes(d.ca)

  it('23 点只会选出轻食或主食/面食, 且 <=20 分钟', () => {
    const late = new Date('2026-09-17T23:30:00')
    expect(resolveMealSlot(late)).toBe('late_night')
    for (let i = 0; i < 30; i += 1) {
      const out = decideOffline({ profile: PROFILE, history: [] }, late)
      expect(out).not.toBeNull()
      expect(LATE_OK(out!.dish)).toBe(true)
      expect(out!.dish.cm).toBeLessThanOrEqual(20)
    }
  })

  it('深夜能吃上碗面了 (改前主食/面食恒为 0)', () => {
    const late = new Date('2026-09-17T23:30:00')
    let stapleOrNoodle = 0
    for (let i = 0; i < 30; i += 1) {
      const out = decideOffline({ profile: PROFILE, history: [] }, late)
      if (out && ['主食', '面食'].includes(out.dish.ca)) stapleOrNoodle += 1
    }
    expect(stapleOrNoodle).toBeGreaterThan(0)
  })

  it('白名单只在深夜生效: 白天仍按老规则出菜', () => {
    const noon = new Date('2026-09-17T12:30:00')
    expect(resolveMealSlot(noon)).toBe('lunch')
    const seen = new Set<string>()
    for (let i = 0; i < 60; i += 1) {
      const out = decideOffline({ profile: PROFILE, history: [] }, noon)
      if (out) seen.add(out.dish.ca)
    }
    // 午餐时段不该被夜宵白名单收窄成"只有主食/面食"
    expect(seen.size).toBeGreaterThan(1)
    expect([...seen].some((ca) => !['主食', '面食'].includes(ca))).toBe(true)
  })

  it('时段推断边界', () => {
    expect(resolveMealSlot(new Date('2026-09-17T04:59:00'))).toBe('late_night')
    expect(resolveMealSlot(new Date('2026-09-17T05:00:00'))).toBe('breakfast')
    expect(resolveMealSlot(new Date('2026-09-17T14:59:00'))).toBe('lunch')
    expect(resolveMealSlot(new Date('2026-09-17T15:00:00'))).toBe('dinner')
  })
})

describe('需求 6: 一句话理由', () => {
  const cases = [
    { daysSinceSpicy: 3 },
    { daysSinceSpicy: 30 },
    { expiringItem: '番茄' },
    { expiringItem: '金针菇炒肉末配菜' },
    { weather: 'rain' },
    { weather: 'snow' },
    { weather: 'hot' },
    { weather: 'cold' },
    { mealSlot: 'late_night' as const },
    { daysSinceDish: 6 },
    { cuisine: '粤式', cuisineRotated: true },
    { inventoryRatio: 0.5 },
    { inventoryRatio: 0.9 },
    {},
    { relaxed: true },
  ]
  it.each(cases)('理由不超过 20 字: %o', (ctx) => {
    expect(buildReason(ctx).length).toBeLessThanOrEqual(20)
  })
})

// 与 Python ReasonService 的逐字基线。
// 两端文案只要有一个字不一样, 联网和断网看到的话术就不一致 —— 这类漂移
// 在真实用户那里表现为"这个 App 说话风格忽变", 很难定位, 所以在单测里钉死。
const REASON_FIXTURES: Array<{ input: Parameters<typeof buildReason>[0]; expected: string }> = [
  { input: { dish: '麻婆豆腐', daysSinceSpicy: 3 }, expected: '你 3 天没吃辣了' },
  { input: { dish: '麻婆豆腐', daysSinceSpicy: 30 }, expected: '你 30 天没吃辣了' },
  { input: { dish: '麻婆豆腐', expiringItem: '番茄' }, expected: '冰箱的番茄快到期了' },
  { input: { dish: '麻婆豆腐', expiringItem: '金针菇炒肉末配菜' }, expected: '冰箱的金针菇炒快到期了' },
  { input: { dish: '麻婆豆腐', weather: 'rain' }, expected: '外面下雨，在家煮锅暖的' },
  { input: { dish: '麻婆豆腐', weather: 'snow' }, expected: '下雪天，来点热乎的' },
  { input: { dish: '麻婆豆腐', weather: 'hot' }, expected: '天热，吃点清爽的' },
  { input: { dish: '麻婆豆腐', weather: 'cold' }, expected: '天冷，喝口热的' },
  { input: { dish: '紫菜蛋花汤', mealSlot: 'late_night' }, expected: '深夜吃点轻的，负担小' },
  { input: { dish: '西湖牛肉羹', mealSlot: 'late_night' }, expected: '深夜吃点轻的，负担小' },
  { input: { dish: '阳春面', mealSlot: 'late_night' }, expected: '夜宵别太重，这个刚好' },
  { input: { dish: '麻婆豆腐', daysSinceDish: 6 }, expected: '这道菜 6 天没上桌了' },
  { input: { dish: '三杯鸡', cuisine: '粤式', cuisineRotated: true }, expected: '换换口味，试试粤式' },
  { input: { dish: '鱼香肉丝', cuisine: '川湘', cuisineRotated: true }, expected: '川湘好久没吃了' },
  { input: { dish: '阳春面', cuisine: '江浙', cuisineRotated: true }, expected: '江浙好久没吃了' },
  { input: { dish: '麻婆豆腐', inventoryRatio: 0.5 }, expected: '家里有一半食材，顺手' },
  { input: { dish: '麻婆豆腐', inventoryRatio: 0.9 }, expected: '家里现成就有，别买了' },
  // 分类词不是菜系: 「换换口味，试试早餐」这类话不能说出口, 整条轮换规则跳过。
  // 跳过之后落到下一条规则(库存/食材); 下一条也不命中就返回空 —— 不兜万能句
  // (旧的「今天这个，不亏。」对每道菜都成立, 万能句比没有更假)。
  { input: { dish: '皮蛋瘦肉粥', cuisine: '早餐', cuisineRotated: true }, expected: '' },
  {
    input: { dish: '阳春面', cuisine: '主食', cuisineRotated: true, inventoryRatio: 0.6 },
    expected: '家里有一半食材，顺手',
  },
  { input: { dish: '麻婆豆腐' }, expected: '' },
  { input: { dish: '麻婆豆腐', relaxed: true }, expected: '可选项不多了，就它吧。' },
]

describe('需求 6: 两端理由逐字一致 (防 Python / TS 漂移)', () => {
  // 标题带前缀: expected 现在是空串也算一种合法输出, 空标题会被 runner 当成没写名字
  it.each(REASON_FIXTURES)('理由: $expected', ({ input, expected }) => {
    expect(buildReason(input)).toBe(expected)
  })

  it('同一道菜永远同一句话 (不用 random 挑说法)', () => {
    const a = buildReason({ dish: '鱼香肉丝', cuisine: '川湘', cuisineRotated: true })
    for (let i = 0; i < 20; i += 1) {
      expect(buildReason({ dish: '鱼香肉丝', cuisine: '川湘', cuisineRotated: true })).toBe(a)
    }
  })
})

describe('需求 10: 极简做法 3-5 步', () => {
  it('候选池里每道菜都是 3-5 步', () => {
    for (const d of LOCAL_DISHES) {
      expect(d.st.length).toBeGreaterThanOrEqual(3)
      expect(d.st.length).toBeLessThanOrEqual(5)
    }
  })
  it('clipSteps 最多 5 步', () => {
    expect(clipSteps(['1', '2', '3', '4', '5', '6', '7']).length).toBe(5)
  })
})

describe('需求 7: 永远有答案', () => {
  it('候选池规模足够支撑 7 天去重', () => {
    expect(LOCAL_DISHES.length).toBeGreaterThanOrEqual(60)
  })
  it('深夜候选不少于 10 道', () => {
    expect(LOCAL_DISHES.filter((d) => d.lt && d.cm <= 20).length).toBeGreaterThanOrEqual(10)
  })
  it('忌口全部命中时仍能出结果(降级放宽)', () => {
    const out = decideOffline({ profile: { ...PROFILE, avoid: ['鸡蛋'] }, history: [] })
    expect(out).not.toBeNull()
  })
})

describe('需求 1: 引导题库', () => {
  it('只有 3 问, 都带跳过路径', () => {
    expect(ONBOARDING_QUESTIONS.length).toBe(3)
    for (const q of ONBOARDING_QUESTIONS) {
      expect(q.options.length).toBeGreaterThan(0)
    }
  })
  it('答案能映射成完整档案(缺的题用默认值补齐)', () => {
    const payload = toPreferencePayload({ flavor: ['spicy'] })
    expect(payload.diet.spice_level).toBe(4)
    expect(payload.diet.cuisines.length).toBeGreaterThan(0)
    expect(payload.household.weekday_cook_minutes).toBeGreaterThan(0)
    expect(Array.isArray(payload.allergy.avoid_ingredients)).toBe(true)
  })
})
