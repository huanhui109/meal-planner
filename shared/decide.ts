/**
 * 饭决离线决策 (需求 7: 永远有答案)
 *
 * 这是服务端 DecisionService 的**客户端同构子集**。断网、超时、后端挂了的时候,
 * 页面靠这份代码 + 本地候选池照常出结果, 结果卡打「本地答案」角标。
 *
 * 为什么要有第二份实现:
 *   断网 = 没有服务端。要"永远有答案"就必须在客户端有算法, 没有别的办法。
 *
 * 代价与约束:
 *   两份实现必须**行为一致**, 否则用户断网时看到的菜和联网时不一样, 这类 bug 极难排查。
 *   所以:
 *     1. 权重、惩罚、归一化别名表全部对齐 backend/app/services/decision_service.py
 *     2. backend/tests/test_decide_parity.py 用同一组输入断言两端输出集合一致
 *     3. 候选池来自同一份 data/local_dish_pool.json (由 gen_local_pool.mjs 生成)
 *   改任何一侧, 都要跑另一侧的测试。
 *
 * 与服务端的能力差(有意为之, 客户端拿不到这些数据):
 *   - 没有库存命中率 (冰箱数据在服务端)
 *   - 没有临期食材
 *   - 历史只来自本地缓存的近期决策, 不含周菜单
 *   - 预算项只在候选带了 cost 时才生效。本地池没有食材用量与参考单价(数据在服务端),
 *     估不出成本就跳过这一项, 断网时的推荐可能比联网时略贵 —— 先保证有答案。
 */
import { LOCAL_DISHES } from './local-pool.generated'
import type { LocalDish } from './local-pool.generated'
import { brand } from './brand'
import type { MealSlot } from './types'

export const MEAL_SLOT_LABELS: Record<MealSlot, string> = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  late_night: '夜宵',
}

/** 与服务端 decision_service.ALIAS_PAIRS 一一对应 */
const ALIAS_PAIRS: Array<[string, string]> = [
  ['西红柿', '番茄'],
  ['马铃薯', '土豆'],
  ['洋芋', '土豆'],
  ['包菜', '卷心菜'],
  ['甘蓝', '卷心菜'],
  // 蛋 vs 鸡蛋: 「番茄炒蛋」和「西红柿炒鸡蛋」必须归一到同一个 key
  ['鸡蛋', '蛋'],
  ['鸡旦', '蛋'],
  ['鸭蛋', '蛋'],
  ['大葱', '葱'],
  ['小葱', '葱'],
]

const PUNCT = /[\s·・,，、\-—_()（）【】[\]]+/g

/** 归一化菜名: 去标点空白 + 别名收敛 */
export function normalizeDishName(name: string): string {
  let text = (name || '').replace(PUNCT, '')
  for (const [from, to] of ALIAS_PAIRS) text = text.split(from).join(to)
  return text
}

export interface OfflineProfile {
  cuisines: string[]
  spiceLevel: number
  avoid: string[]
  /** 出餐时间上限(分钟) */
  cookCap: number
  /** 这一餐的预算上限(元): 日预算 ÷ 当日餐次; 用户没设过预算就不传 */
  mealBudget?: number | null
}

export interface DecideHistoryItem {
  name: string
  category?: string
  cuisine?: string
  main?: string
  /** yyyy-mm-dd */
  date: string
}

export interface DecideWeather {
  condition?: string | null
  temp_c?: number | null
}

export interface DecideContext {
  profile: OfflineProfile
  history: DecideHistoryItem[]
  weather?: DecideWeather | null
  /** 本次会话已拒绝的菜名 */
  exclude?: string[]
  /** 食材命中率 0-1, 离线场景通常给 0 */
  inventoryRatio?: number
}

export interface DecideOutcome {
  dish: LocalDish
  reason: string
  mealSlot: MealSlot
  source: 'offline'
  relaxed: boolean
  /** R-10: 放宽到第几档。0 = 一档没松 */
  relaxedLevel: number
  /** R-10: 放宽**之前**的候选池大小, 与服务端 candidate_count 同口径 */
  candidateCount: number
}

/**
 * 权重 —— 必须与 config/default.yaml 的 decide 段一致
 *
 * cuisine 归 0: recipe.cuisine 列现在存的是菜品分类(荤菜/主食/早餐…), 不是菜系,
 * 与用户档案里的真菜系(川湘/粤菜/江浙/日料/家常)对不上 —— 全库 396 道只命中 2 道。
 * 保留权重就等于让一个永远打不中的规则占着权重位, 还会挤掉库存/天气的真实区分度。
 * 本期不做 cuisine 清洗: 真菜系由凌晨 LLM 富集任务标注回填后再恢复 20
 * (必须同步改 backend/app/config.py 与 config/default.yaml)。
 */
const SCORE = {
  cuisine: 0,
  spice: 15,
  inventory: 25,
  weather: 18,
  budget: 15,
  budgetOverTolerance: 1.2,
  categoryPenalty: 25,
  sameCuisinePenalty: 15,
  mainIngredientPenalty: 40,
  randomBand: 5,
  minChoices: 3,
  noRepeatDays: 7,
  lateNightMaxMinutes: 20,
}

const STAPLES = [
  '盐', '食用油', '糖', '生抽', '老抽', '香油', '淀粉', '料酒', '白胡椒', '黑胡椒',
]

/**
 * 葱 / 姜 / 蒜 —— 2026-09-23 判定「不做」, 整件排 V1.3。与服务端同口径(必须同步)。
 *
 * 问题仍在: 它们几乎出现在每一道中式菜里, 录了葱姜蒜的冰箱会让大批菜凭空拿到
 * 库存加分, FULL=2 提前饱和 (11 样时 52.3% 的菜拿满分), 区分度归零。
 *
 * 为什么不做 (判据: 排序修复不得让用户可见文案的触发率变化超过 ±5pp):
 *   剔除范围一变, neededIngredients 这个**同时是分子(hits)和分母(len)**的函数
 *   就跟着变, 连带改动「交给外卖吧」(ratio < 0.3) 的触发率。服务端实测三个方案
 *   (精确串 / 扩 STAPLES / 子串+蔬菜白名单) 全部超 ±5pp, 最大 +14.7pp。
 *   不是改得不够巧, 而是两个消费点共用一套 need, 动一个必动另一个。
 *
 * V1.3: 把 need 拆两份 —— 排序用去调味料的, 文案继续用现有的。那是文案口径的
 * 产品决策, 不是排序决策。
 */
/** 这道菜真正要买的食材 (去掉调味料) —— 分子与分母都用它, 与服务端一致 */
function neededIngredients(dish: LocalDish): string[] {
  return dish.ig.filter((i) => !STAPLES.includes(i))
}

/**
 * 夜宵额外放行的品类 —— 与服务端 decision_service.LATE_NIGHT_EXTRA_CATEGORIES 一致
 *
 * 深夜只有 is_light 一道闸的时候, 池子里主食/面食为 0, "想吃碗面"是无解的。
 * 这里同样只在这一个深夜分支生效, 绝不回头去改 light 标记 —— 白天"来点清淡的"
 * 还要靠 light, 把蛋炒饭标成轻食等于修一个问题制造另一个问题。
 */
const LATE_NIGHT_EXTRA_CATEGORIES = ['主食', '面食']

/** 抽签池水位线 (R-10), 与服务端 POOL_MIN 一致 */
const POOL_MIN = 8

/** 放宽阶梯的最高档, 与服务端 MAX_RELAX_LEVEL 一致 */
export const MAX_RELAX_LEVEL = 4

/**
 * 每档的名字, 与服务端 RELAX_LEVEL_* 同名:
 * 埋点/看板的阈值一律引用这两个名字, 不要在别处写数字 —— J3 的门槛已经漂过三次。
 */
export const RELAX_LEVEL_CATEGORY_SPREAD = 2 // 松到这一档 = 同品类打散不再扣分
export const RELAX_LEVEL_NO_REPEAT = 4 // 松到这一档 = 「近 7 天不重复」也失效

/**
 * R-09 库存打分归一化 —— 与服务端同名常量一致
 *
 * 旧口径 `score_inventory * (hits / 这道菜自己的食材数)` 奖励的是"食材少的简单菜"
 * (2 样食材的菜录中 1 样就满分), 而且 25 分的幅度是 random_band 的 5 倍 ——
 * 录了食材之后抽签带从 60 道塌到 3 道。改成 命中数 / 固定分母, 并把整个库存家族
 * (命中加分 + 临期加分) 合起来封顶在 random_band。
 */
// 为什么是 2 (data-analyst A22 定标, 真库 342 道实测):
//   FULL=3 ✗ 真实小冰箱 hits 分布 0:234 / 1:99 / 2:8 / 3:1, 只有 1 道菜(0.3%)能拿满,
//            主流只拿到 1.67/5 = 33%, R-09 等于没接线;
//   FULL=1 ✗ 完全二元, 大冰箱(8 样)下 74.6% 的菜同分, 库存信号区分度归零;
//   FULL=2 ✓ 小冰箱主流拿 2.5/5 半档, 保住"1 样 < 2 样"的区分,
//            三个库存集 natural_band 54 / 70 / 95 全健康。
// 命中分布变了就要重新定标, 不要凭手感改这个数字。
const INVENTORY_HITS_FULL = 2
// 档位落成 0 / 2 / 4 (见 inventoryScore), 跨度 4, 距 random_band 留 1 余量。
// R-14 指出默认场景下打分实际只有辣度一个维度在工作 —— R-09 是唯一能让打分真正
// 多维的入口, 压到 3 会让它掉到噪声量级; 外层还有 SOFT_PREFERENCE_CAP 兜着整包。
// 谁改 random_band 必须回头重算这个上限。
const INVENTORY_SCORE_CAP = 4

/**
 * meal_slots 软惩罚 (R-11) —— 与服务端同名常量一致。只加分不减分。
 *
 * ⚠️ 幅度必须 <= SCORE.randomBand (5.0)。抽签是"距最优分 5 分以内都参与", 所以幅度
 * 一旦超过它, band 里就只剩一侧的菜 —— 减分侧是「准硬过滤」(被罚菜全出局),
 * 加分侧是「band 独占」(受加分菜抬高最优分、把其他人挤出带)。同一枚硬币的两面。
 * 实测: +12/-20 会让晚饭变成"连点 12 次全是汤", +3/0 才回到自然占比附近。
 *
 * 减分置 0: 覆盖率两成多, 减分命中与否几乎取决于标注有没有做 —— 拿一群菜的"标注
 * 运气"去压另一群, 不如不罚。
 */
const MEAL_SLOT_MATCH_BONUS = 3
const MEAL_SLOT_MISMATCH_PENALTY = 0

/**
 * 早餐代理补偿 —— 与服务端同名常量一致。
 *
 * meal_slots 覆盖率只有两成多, 早餐档不能只靠标注。但也不能照旧口径给 12 / 8:
 * 那两个数是 randomBand(5) 的 2.4 倍和 1.6 倍, 两项全中叠到 20 分 ——
 * 早餐档的抽签带会被这两笔直接切成「主食快手 / 其它」两半。
 *
 * 改由品类(主食/面食) 与出餐时间(<=15min) 两个代理信号补位, 3 + 1.5 = 4.5 < 5。
 *
 * ⚠️ 与餐次贴合**取最大值, 不叠加** (见 scoreOf): 两者是同一信号("这道菜适不适合
 * 早餐")的两个来源, 单独叠加会让三项全中的菜拿到 7.5 > band。
 *   2026-09-23 实测过叠加(方案「叠加 7.5」)并被回退: 门禁改为结果判红后, 它在
 *   4 场景 × 补标前后 8 格里挂了 2 格。**别再试同样的改动而不先看那 8 格。**
 * ⚠️ 也不能改成"标了就跳过补偿": 那样标了 breakfast 只拿 3、没标的主/面拿 4.5,
 *    代理分反而高于显式标注分 —— 标得越全分越低, 没人愿意补标注。
 */
const BREAKFAST_CATEGORY_BONUS = 3
const BREAKFAST_QUICK_BONUS = 1.5

/**
 * 软偏好包上限。⚠️ 是"不得超过"的上限, 不是"建议取到"的值。
 *
 * 为什么是"包": 单项各自 <= randomBand 挡不住它们叠起来穿 ——
 * 早餐补偿 4.5 + 库存命中 4 = 8.5, 单项都合规, 合起来照样能切带。
 * 包内成员: 餐次贴合 / 早餐补偿(两者取 max 后进包) / 库存命中。
 *
 * 为什么是 4 而不是 randomBand(5): 留 1 的余量, 与 INVENTORY_SCORE_CAP 同一条规矩。
 * 封顶取成 band 本身时零余量 —— 未命中那组要 base 分落在 0 分以内才进得来,
 * 软偏好包会退化成准硬过滤。
 *
 * ⚠️ 服务端那侧的包里还有一项 intent.bonus()(口语诉求): 离线端没有口语解析,
 *    少这一项是唯一一处有意的差异, 别当漂移去"修"。
 * ⚠️ 同理, 服务端的 prefer_fridge 放大命中数(PREFER_FRIDGE_MULTIPLIER)也不属于
 *    包成员 —— 它是放大系数不是加分项, 离线端没有 intent 所以天然没有这一侧。
 * ⚠️ weatherScore 不进包: 幅度是 SCORE.weather(18), 是 band 的 3.6 倍。
 */
const SOFT_PREFERENCE_CAP = 4

const FALLBACK_REASON = '可选项不多了，就它吧。'
const REASON_MAX = 20

// 同义说法池。与 Python reason_service.py 的 _LATE_NIGHT_LINES / _ROTATION_TEMPLATES
// 必须逐字一致 —— 两端文案不一致, 用户联网和断网看到的话术就不一样了。
// 原因: 这两条规则命中率极高, 连点几次都是同一句模板会让"理由"显得假。
const LATE_NIGHT_LINES = ['深夜吃点轻的，负担小', '夜宵别太重，这个刚好', '睡前吃这个，不撑']
const ROTATION_TEMPLATES = [
  '换换口味，试试{cuisine}',
  '{cuisine}好久没吃了',
  '来点{cuisine}，换个节奏',
]

/**
 * 菜品分类词表 —— 这些不是菜系。
 *
 * 菜谱库的 cuisine 列历史上存的是分类(荤菜/主食/早餐…)。直接套进轮换模板会生成
 * 「换换口味，试试早餐」「来点半成品加工，换个节奏」: 句子通, 但摆在结果卡上很荒谬,
 * 用户一眼看出 App 不知道自己在说什么。命中这些值时整条轮换规则跳过, 退回后面的规则。
 *
 * 本期不做 cuisine 列清洗: 真菜系由凌晨 LLM 富集任务标注回填。回填完成后这张表
 * 连同命中逻辑可以一起删掉。
 *
 * ⚠️ 这张表是唯一真源, backend/app/services/reason_service.py 的
 * _GENERIC_CUISINE_LABELS 是它的副本。改这里必须同步改那边, 否则联网和断网的话术不一致。
 */
const GENERIC_CUISINE_LABELS = new Set([
  '荤菜', '素菜', '主食', '面食', '汤羹', '汤与粥', '凉菜',
  '小吃', '早餐', '饮品', '甜品', '半成品加工', '调味品', '水产',
  '调料', '半成品',
])

/** 按菜名稳定挑一种说法 —— 不能用 Math.random, 同一道菜两次说法不同会很假 */
function variant(pool: string[], key?: string | null): string {
  if (!pool.length) return ''
  let seed = 0
  for (const ch of key || '') seed += ch.charCodeAt(0)
  return pool[seed % pool.length]
}

/** 时段推断: 22:00-05:00 是夜宵, 与服务端一致 */
export function resolveMealSlot(date: Date = new Date()): MealSlot {
  const hour = date.getHours()
  if (hour >= 22 || hour < 5) return 'late_night'
  if (hour < 10) return 'breakfast'
  if (hour < 15) return 'lunch'
  return 'dinner'
}

function daysBetween(from: string, to: string): number {
  const a = Date.parse(`${from}T00:00:00`)
  const b = Date.parse(`${to}T00:00:00`)
  if (Number.isNaN(a) || Number.isNaN(b)) return 0
  return Math.max(0, Math.round((b - a) / 86400000))
}

/**
 * 家里现有的食材命中了几样 —— R-09 排序用的分子, 与服务端 _inventory_hits 一致
 *
 * 分母不再取这道菜自己的食材数: 那样"2 样食材的菜录中 1 样"就满分,
 * 等于奖励食材少的简单菜。固定分母见 INVENTORY_HITS_FULL。
 */
function inventoryHits(dish: LocalDish, owned: string[]): number {
  if (!owned.length) return 0
  const need = neededIngredients(dish)
  if (!need.length) return 0
  return need.filter((i) => owned.some((o) => o.includes(i) || i.includes(o))).length
}

/** 命中率 hits/len(need) —— 只供天气加分用, R-09 一行不改 (服务端同口径) */
function inventoryRatio(dish: LocalDish, owned: string[]): number {
  if (!owned.length) return 0
  const need = neededIngredients(dish)
  if (!need.length) return 0
  return inventoryHits(dish, owned) / need.length
}

/**
 * 库存家族的排序加分, 与服务端 _inventory_score 一致: 连续型, 且合起来不超过上限。
 * 为什么封顶见 INVENTORY_SCORE_CAP 处的说明 —— 幅度超过 random_band 就会把
 * 抽签带切成"抽得到 / 抽不到"两半。
 */
function inventoryScore(dish: LocalDish, owned: string[], suppliedRatio = 0): number {
  const capped = Math.min(SCORE.inventory, INVENTORY_SCORE_CAP)
  // 离线没有冰箱数据, 但调用方可以传一个命中率进来; 那条信号不能因为它不是
  // 命中数就丢掉 —— 按比例折算, 同样封顶。
  if (!owned.length) {
    return suppliedRatio > 0 ? capped * Math.min(suppliedRatio, 1) : 0
  }
  const hits = inventoryHits(dish, owned)
  return (capped * Math.min(hits, INVENTORY_HITS_FULL)) / INVENTORY_HITS_FULL
}

/** 极简做法: 严格 3-5 步 (需求 10) */
export function clipSteps(steps: string[]): string[] {
  const items = (steps || []).filter((s) => s && s.trim())
  return items.length > 5 ? items.slice(0, 5) : items
}

export function buildReason(input: {
  /** 菜名, 只用于在同一种规则里挑说法变体 */
  dish?: string | null
  daysSinceSpicy?: number | null
  daysSinceDish?: number | null
  expiringItem?: string | null
  weather?: string | null
  mealSlot?: MealSlot
  cuisine?: string
  cuisineRotated?: boolean
  inventoryRatio?: number
  relaxed?: boolean
}): string {
  if (input.relaxed) return clip(FALLBACK_REASON)
  const c: Array<string | null> = []
  if (input.daysSinceSpicy != null && input.daysSinceSpicy >= 3) {
    c.push(`你 ${input.daysSinceSpicy} 天没吃辣了`)
  }
  if (input.expiringItem) {
    c.push(`冰箱的${input.expiringItem.slice(0, 4)}快到期了`)
  }
  if (input.weather === 'rain') c.push('外面下雨，在家煮锅暖的')
  else if (input.weather === 'snow') c.push('下雪天，来点热乎的')
  else if (input.weather === 'hot') c.push('天热，吃点清爽的')
  else if (input.weather === 'cold') c.push('天冷，喝口热的')
  if (input.mealSlot === 'late_night') c.push(variant(LATE_NIGHT_LINES, input.dish))
  if (input.daysSinceDish != null && input.daysSinceDish >= 6) {
    c.push(`这道菜 ${input.daysSinceDish} 天没上桌了`)
  }
  // 分类词不是菜系, 说出来那句话是废话 (见 GENERIC_CUISINE_LABELS 的说明)
  if (input.cuisineRotated && input.cuisine && !GENERIC_CUISINE_LABELS.has(input.cuisine)) {
    c.push(variant(ROTATION_TEMPLATES, input.dish).replace('{cuisine}', input.cuisine))
  }
  // ⚠️ 这里曾经有一条 `${minutes} 分钟搞定，不误事`, 2026-09-23 整条摘掉:
  // cook_minutes 是规则回填的品类基准值不是实测(全库 119 道菜都是 22 = 荤菜默认值),
  // 拿它说"20 分钟搞定"是**假精确**。时间维度只留在引擎内部(出餐上限 / 深夜阈值),
  // 对外只给结果卡上的档位词。别把它加回来 —— 加回来要同步改 Python 侧。
  if ((input.inventoryRatio ?? 0) >= 0.8) c.push('家里现成就有，别买了')
  else if ((input.inventoryRatio ?? 0) >= 0.5) c.push('家里有一半食材，顺手')

  for (const text of c) {
    if (text) return clip(text)
  }
  // 一条都没命中就说实话: 没有。不兜「今天这个，不亏。」这类万能句 ——
  // 它对每道菜都成立, 摆在这儿只会让人以为 App 看出了什么。
  // ⚠️ 与 app/services/reason_service.py 的 build() 同口径, 改一侧必须改另一侧。
  return ''
}

function clip(text: string): string {
  return REASON_MAX > 0 && text.length > REASON_MAX ? text.slice(0, REASON_MAX) : text
}

/**
 * 离线决策主函数。纯函数, 不碰网络/存储, 好测。
 * 返回 null 只在候选被榨干时发生 —— 本地池 ≥60 道, 正常不会走到。
 */
export function decideOffline(
  ctx: DecideContext,
  now: Date = new Date(),
  pool: LocalDish[] = LOCAL_DISHES,
): DecideOutcome | null {
  const today = toDateKey(now)
  const slot = resolveMealSlot(now)
  const excluded = new Set((ctx.exclude || []).map(normalizeDishName))
  const avoid = ctx.profile.avoid || []

  const recent = ctx.history || []
  const recentNames = new Set<string>()
  const categoryCount: Record<string, number> = {}
  const cuisineCount: Record<string, number> = {}
  const dishLastSeen: Record<string, string> = {}
  const sorted = [...recent].sort((a, b) => (a.date < b.date ? 1 : -1))

  sorted.forEach((item, idx) => {
    const key = normalizeDishName(item.name)
    if (daysBetween(item.date, today) <= SCORE.noRepeatDays) recentNames.add(key)
    if (!dishLastSeen[key]) dishLastSeen[key] = item.date
    if (idx < 3) {
      if (item.category) categoryCount[item.category] = (categoryCount[item.category] || 0) + 1
      if (item.cuisine) cuisineCount[item.cuisine] = (cuisineCount[item.cuisine] || 0) + 1
    }
  })

  const last = sorted[0]
  const lastMain = last?.main
  const lastCuisine = last?.cuisine

  const passes = (
    d: LocalDish,
    opts: { noRepeat: boolean; cookCap: number | null; lateNight: boolean },
  ): boolean => {
    const haystack = [d.n, ...d.ig].join(' ')
    if (avoid.some((word) => word && haystack.includes(word))) return false
    if (excluded.has(normalizeDishName(d.n))) return false
    if (opts.noRepeat && recentNames.has(normalizeDishName(d.n))) return false
    if (opts.lateNight) {
      // 轻食, 或主食/面食类的快手菜。时间上限对白名单菜同样生效。
      if (!d.lt && !LATE_NIGHT_EXTRA_CATEGORIES.includes(d.ca)) return false
      if (d.cm > SCORE.lateNightMaxMinutes) return false
    }
    if (opts.cookCap != null && d.cm > opts.cookCap) return false
    return true
  }

  /**
   * 5 档放宽阶梯, 顺序与服务端 _relax_ladder 一致
   *
   * 0 全硬规则 / 1 松时间 / 2 松品类打散 / 3 松主料两餐不重样 / 4 松近 7 天不重复。
   * tools 与 meal_slots 不进这条阶梯: meal_slots 走 R-11 的只加分不减分, 理由见服务端注释。
   */
  const ladder = [
    { cookCap: ctx.profile.cookCap, noCategoryPenalty: false, noMainPenalty: false, noRepeat: true },
    { cookCap: null, noCategoryPenalty: false, noMainPenalty: false, noRepeat: true },
    { cookCap: null, noCategoryPenalty: true, noMainPenalty: false, noRepeat: true },
    { cookCap: null, noCategoryPenalty: true, noMainPenalty: true, noRepeat: true },
    { cookCap: null, noCategoryPenalty: true, noMainPenalty: true, noRepeat: false },
  ]

  const isLateNight = slot === 'late_night'
  // 天花板 = 全松之后最多能有多少菜。全库不足水位线时不该一路松到最深那档 ——
  // 池子一点没变大, 用户却吃到了昨天刚吃过的菜。
  const ceiling = pool.filter((d) => passes(d, { lateNight: isLateNight, cookCap: null, noRepeat: false })).length
  if (!ceiling) return null
  const target = Math.min(POOL_MIN, ceiling)

  let relaxedLevel = 0
  let relax = ladder[0]
  let candidates: LocalDish[] = []
  let candidateCount = 0
  for (let i = 0; i <= MAX_RELAX_LEVEL; i += 1) {
    relax = ladder[i]
    relaxedLevel = i
    candidates = pool.filter((d) =>
      passes(d, { lateNight: isLateNight, cookCap: relax.cookCap, noRepeat: relax.noRepeat }),
    )
    if (i === 0) candidateCount = candidates.length
    if (candidates.length >= target) break
  }
  if (!candidates.length) return null

  const weather = ctx.weather?.condition ?? null
  const owned: string[] = []
  const ratio = ctx.inventoryRatio ?? 0

  const scoreOf = (d: LocalDish): number => {
    let s = 0
    if (ctx.profile.cuisines.length && ctx.profile.cuisines.includes(d.cu)) s += SCORE.cuisine
    const gap = Math.abs(d.sp - ctx.profile.spiceLevel) / 4
    s += SCORE.spice * Math.max(0, 1 - gap)
    // 天气: 幅度是 band 的 3.6 倍, 不在软偏好包里 —— 见 SOFT_PREFERENCE_CAP
    s += weatherScore(d, weather, ratio || inventoryRatio(d, owned))
    // 预算贴合: 权重与容差对齐 config/default.yaml 的 decide 段。
    // 本地池没带食材用量, 估不出成本的菜不奖不罚。
    const budget = ctx.profile.mealBudget
    const cost = (d as LocalDish & { cost?: number }).cost
    if (budget && budget > 0 && typeof cost === 'number') {
      if (cost <= budget) s += SCORE.budget
      else if (cost <= budget * SCORE.budgetOverTolerance) s += SCORE.budget * 0.4
      else s -= SCORE.budget
    }
    // ---- 软偏好包: 餐次贴合 / 早餐补偿 / 库存命中 ----
    // 三项都是"倾向", 合成一个包再整体封顶, 与服务端一致 (见 SOFT_PREFERENCE_CAP)
    let soft = 0

    const slotScore = mealSlotScore(d, slot)

    // 早餐代理补偿: 只在"没标注"或"标注含早餐"时给 —— 显式标成别的餐次就不给
    // ⚠️ 与餐次贴合**取最大值, 不叠加** (见 BREAKFAST_CATEGORY_BONUS 处的说明):
    //   2026-09-23 试过叠加(方案「叠加 7.5」)并被回退 —— 门禁的结果判红在
    //   4 场景 × 补标前后 8 格里挂了 2 格。**不要为它加防塌兜底。**
    let breakfastComp = 0
    if (slot === 'breakfast' && (!d.ms || d.ms.includes(slot))) {
      if (d.ca === '主食' || d.ca === '面食') breakfastComp += BREAKFAST_CATEGORY_BONUS
      if (d.cm <= 15) breakfastComp += BREAKFAST_QUICK_BONUS
    }

    soft += Math.max(slotScore, breakfastComp)
    // 库存: 排序走命中数 (R-09), 天气走命中率 —— 两个语义, 与服务端一致
    soft += inventoryScore(d, owned, ratio)
    s += Math.min(soft, SOFT_PREFERENCE_CAP)
    if (!relax.noCategoryPenalty) {
      if (d.ca) s -= SCORE.categoryPenalty * (categoryCount[d.ca] || 0)
      if (d.cu && d.cu === lastCuisine) s -= SCORE.sameCuisinePenalty
    }
    if (!relax.noMainPenalty && lastMain && d.mi && lastMain === d.mi) {
      s -= SCORE.mainIngredientPenalty
    }
    return s
  }

  const scored = candidates.map((d) => ({ s: scoreOf(d), d }))
  scored.sort((a, b) => b.s - a.s)
  // 软随机池: 分差在 band 之内的都参与抽签。
  // 不能先取 top N 再在 N 个里随机 —— 那样连点几次会在固定几道菜之间来回横跳。
  let band = scored.filter((x) => x.s >= scored[0].s - SCORE.randomBand).map((x) => x.d)
  if (band.length < SCORE.minChoices) {
    band = scored.slice(0, SCORE.minChoices).map((x) => x.d)
  }
  if (!band.length) band = [scored[0].d]
  const picked = band[Math.floor(Math.random() * band.length)]

  const seen = dishLastSeen[normalizeDishName(picked.n)]
  const daysSinceDish = seen ? daysBetween(seen, today) : null
  const daysSinceSpicy = null // 离线没有辣度流水, 交给服务端
  const reason = buildReason({
    dish: picked.n,
    daysSinceSpicy,
    daysSinceDish,
    weather,
    mealSlot: slot,
    cuisine: picked.cu,
    cuisineRotated: Boolean(picked.cu && picked.cu !== lastCuisine),
    inventoryRatio: ratio,
    relaxed: relaxedLevel > 0,
  })

  return {
    dish: picked,
    reason,
    mealSlot: slot,
    source: 'offline',
    relaxed: relaxedLevel > 0,
    relaxedLevel,
    candidateCount,
  }
}

/**
 * meal_slots 软惩罚 (R-11) —— 与服务端 _meal_slot_score 一致
 *
 * ⚠️ 夜宵冲突的处理必须与服务端一致: 深夜里命中主食/面食白名单的一律跳过餐次打分,
 * 否则刚被白名单放进池子的面又被这条压回去, 两个改动互相抵消。
 */
function mealSlotScore(d: LocalDish, slot: MealSlot): number {
  if (slot === 'late_night' && LATE_NIGHT_EXTRA_CATEGORIES.includes(d.ca)) return 0
  // ms 由 scripts/gen_local_pool.mjs 从 data/local_dish_pool.json 的 slots 生成;
  // null = "没标注" = 不限制, 与服务端 json_list(None) -> [] 同义。
  if (!d.ms || !d.ms.length) return 0
  return d.ms.includes(slot) ? MEAL_SLOT_MATCH_BONUS : MEAL_SLOT_MISMATCH_PENALTY
}

function weatherScore(d: LocalDish, condition: string | null, ratio: number): number {
  if (!condition) return 0
  const tags = d.tg
  if (condition === 'rain' || condition === 'snow') {
    let s = 0
    if (ratio >= 0.3) s += SCORE.weather
    else if (ratio >= 0.1) s += SCORE.weather * 0.5
    if (tags.some((t) => ['汤羹', '炖煮', '一锅出', '雨天'].includes(t))) s += SCORE.weather * 0.6
    return s
  }
  if (condition === 'hot') {
    let s = 0
    if (tags.includes('清爽') || tags.includes('凉拌') || d.ft.includes('清爽')) s += SCORE.weather
    if (d.sp >= 3 || tags.includes('热辣')) s -= 15
    return s
  }
  if (condition === 'cold') {
    let s = 0
    if (tags.some((t) => ['汤羹', '炖煮', '热辣'].includes(t)) || d.ft.includes('辣')) {
      s += SCORE.weather
    }
    if (tags.includes('凉拌') || d.ca === '凉菜') s -= 20
    return s
  }
  return 0
}

export function toDateKey(d: Date): string {
  const y = d.getFullYear()
  const m = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 结果卡角标文案: 断网时明确告诉用户这是本地答案 (需求 7) */
export const OFFLINE_BADGE = brand.offlineBadge
