/**
 * 饭决决策 store
 *
 * 为什么决策状态要放全局而不是挂在页面上:
 * 用户在结果卡上点「看做法」会开全屏浮层, 页面组件可能被卸载/重挂,
 * 状态挂在组件上会导致结果丢失。跟 useGenerationStore 一个道理。
 *
 * 四条关键行为:
 *   1. 断网/超时 → 自动切离线决策, 结果卡打「本地答案」角标 (需求 7)
 *   2. 连续决策到分档阈值 → 弹倔强提示: 深夜 2 次 / 工作日 3 次 / 周末 5 次
 *      (一刀切锁 3 次对"周末在配一桌菜"的人是负体验, 见 @shared/decide-context)
 *   3. 离线决策的历史写本地, 联网补报, 保证"近 7 天不重复"在离线时也尽量成立
 *   4. utterance 永远可空: 空着按就是无条件决策; 听不懂(`understood=false`)
 *      当作没听见, 不回显任何东西, 照常出菜
 */
import { create } from 'zustand'
import {
  cookDecision,
  decide,
  getDecideProfile,
  getLastDecision,
  sendDecideFeedback,
} from '../api/decide'
import {
  decideOffline,
  resolveMealSlot,
  toDateKey,
  type DecideHistoryItem,
  type DecideOutcome,
  type OfflineProfile,
} from '@shared/decide'
import { contextBucket, stubbornAfter } from '@shared/decide-context'
import { applyServerLayoutVersion } from '../lib/layout-version'
import { track } from '../lib/track'
import type { DecisionResult, MealSlot } from '../types'

const HISTORY_KEY = 'meal-planner:decide-history:v1'
const PROFILE_KEY = 'meal-planner:decide-profile:v1'

/** 点主按钮时这次算什么: 换掉当前 / 周末再加一道 / 首次或改条件后重来 */
export type RollIntent = 'reroll' | 'another_dish' | 'fresh'

/** `/decide/{id}/cook` 返回里一行被消耗/没扣到的食材 */
export type CookConsumeLine = {
  ingredient_name: string
  quantity: number
  unit: string
}

/**
 * 「做完了」的结果。**必须逐档区分**, UI 不能一律显示"已扣减"。
 *
 * 扣不到的几种情况都是真实且用户能察觉的(离线菜谱 / 重复点击 / 缺料 / 服务端失败),
 * 统一说成成功就是在骗人。2.7.0 之前正因为后端没有这条接口, 才只能打个点了事 ——
 * 现在有真结果了, 就必须把结果如实交出去, 由 UI 决定怎么措辞。
 */
export type CookDoneAck =
  /** 压根没有结果, 不该发生 */
  | { kind: 'none' }
  /** 离线兜底出的结果 (id=0): 服务端没有这条决策记录, 没有东西可扣 */
  | { kind: 'skipped' }
  /** 后端没有这道菜的 recipe_id (离线/本地菜): 只置了标记, 没扣减 */
  | { kind: 'no_recipe' }
  /** 幂等命中: 这顿之前已经做完并扣过 */
  | { kind: 'already' }
  | { kind: 'done'; consumed: CookConsumeLine[]; missing: CookConsumeLine[] }
  /** 请求失败: "做完了"这个事实成立, 但扣库存这一步没成功 */
  | { kind: 'failed' }

/** `/decide/understand` 的解析结果中, 前端真正用到的几个字段 */
export type UnderstoodIntent = {
  understood: boolean
  /** 回显给用户看的一句话约束, 例如 ['清淡', '不辣'] */
  echo: string[]
}

type OfflineResult = {
  name: string
  cuisine: string
  category: string
  cover_text: string
  cook_minutes: number
  calories: number
  difficulty: number
  main_ingredient: string
  ingredients: string[]
  steps: string[]
}

/**
 * 后端 R-07 落地后, /decide 会直接下发 relaxed_level 与 candidate_count。
 * 现在先用可选字段接着, 取不到就上报 null —— 不拿本地猜的数冒充引擎指标。
 * layout_version 同理: R-16 后端未下发前一律可空。
 */
type DecisionResultExt = DecisionResult & {
  relaxed_level?: number | null
  candidate_count?: number | null
  layout_version?: string | null
}

function toResult(outcome: DecideOutcome): DecisionResult {
  const d = outcome.dish
  const dish: OfflineResult = {
    name: d.n,
    cuisine: d.cu,
    category: d.ca,
    cover_text: d.cv,
    cook_minutes: d.cm,
    calories: d.kcal,
    difficulty: d.df,
    main_ingredient: d.mi,
    ingredients: [...d.ig],
    steps: [...d.st],
  }
  return {
    id: 0,
    dish,
    reason: outcome.reason,
    meal_slot: outcome.mealSlot,
    meal_slot_label: '',
    source: 'offline',
    weather: {},
    advice: null,
    relaxed: outcome.relaxed,
    decided_at: new Date().toISOString(),
  }
}

function readHistory(): DecideHistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    return raw ? (JSON.parse(raw) as DecideHistoryItem[]) : []
  } catch {
    return []
  }
}

function readProfile(): OfflineProfile | null {
  try {
    const raw = localStorage.getItem(PROFILE_KEY)
    return raw ? (JSON.parse(raw) as OfflineProfile) : null
  } catch {
    return null
  }
}

type State = {
  result: DecisionResult | null
  loading: boolean
  /** 本次会话连续决策次数 (用于倔强提示) */
  round: number
  /** 倔强提示是否已弹过 —— 一次会话只弹一次, 弹两次就成了骚扰 */
  stubbornShown: boolean
  error: string
  /** 结果是否来自离线兜底 */
  offline: boolean
  slot: MealSlot

  /** 一次"打开首页 → 定下来"的会话标识, 由 lib/track 生成并贯穿所有事件 */
  sessionId: string
  /** 用户说的一句话诉求, 永远可空 */
  utterance: string
  /** 解析结果: 只有 understood=true 才不是 null, 前端据此回显 */
  intent: UnderstoodIntent | null
  /** 「换一个」换掉的菜 + 周末「再来一个」定下的菜, 都不再回来 */
  excluded: string[]
  /** 周末「再来一个」定下的菜名, 用于"今晚已定 N 道" */
  picked: string[]
  /** 当前结果卡出现的时刻, 用于算 decide_accept 的犹豫时长 */
  resultShownAt: number

  ensure: () => Promise<void>
  roll: (opts?: { intent?: RollIntent; utterance?: string }) => Promise<DecisionResult | null>
  feedback: (liked: boolean) => Promise<void>
  setUtterance: (text: string, intent?: UnderstoodIntent | null) => void
  accept: () => void
  viewSteps: () => void
  cookStart: () => void
  cookDone: () => Promise<CookDoneAck>
  noteStubbornShown: (date?: Date) => void
  reset: () => void
}

export const useDecideStore = create<State>((set, get) => ({
  result: null,
  loading: false,
  round: 0,
  stubbornShown: false,
  error: '',
  offline: false,
  slot: resolveMealSlot(),

  sessionId: '',
  utterance: '',
  intent: null,
  excluded: [],
  picked: [],
  resultShownAt: 0,

  /** 冷启动: 先拿上次结果秒开, 顺带把档案缓存下来给离线用 */
  ensure: async () => {
    if (get().result) return
    set({ slot: resolveMealSlot() })
    try {
      const [last, profile] = await Promise.all([
        getLastDecision().catch(() => null),
        getDecideProfile().catch(() => null),
      ])
      if (last) set({ result: last, offline: false })
      if (profile) {
        localStorage.setItem(
          PROFILE_KEY,
          JSON.stringify({
            cuisines: profile.cuisines,
            spiceLevel: profile.spice_level,
            avoid: [...profile.avoid, ...profile.allergens],
            cookCap: profile.cook_cap || 60,
            mealBudget: profile.meal_budget ?? null,
          } as OfflineProfile),
        )
      }
    } catch {
      // 首屏拿不到就算了, 用户按一下就有结果
    }
  },

  roll: async (opts) => {
    const state = get()
    const intent: RollIntent = opts?.intent ?? (state.result ? 'reroll' : 'fresh')
    const utterance = (opts?.utterance ?? state.utterance).trim()
    const rerollIndex = state.round

    // 「换一个」= 不要这个。除了换菜, 必须同时上报 reject ——
    // 现状前端从不调 feedback(false), 导致 decision_log.accepted 有 85.3% 是 NULL,
    // "采纳率"这个指标等于没有。这条是把埋点缺口补上, 不是产品逻辑变化。
    if (intent === 'reroll' && state.result) {
      track('decide_reject', {
        decision_id: state.result.id || null,
        dish: state.result.dish.name,
        reroll_index: rerollIndex,
        meal_slot: state.result.meal_slot,
        result_age_ms: state.resultShownAt ? Date.now() - state.resultShownAt : null,
      })
      void get().feedback(false)
    }
    if (intent === 'reroll') {
      track('decide_reroll', { reroll_index: rerollIndex, reroll_intent: 'reroll' })
    }
    if (intent === 'another_dish') {
      track('decide_reroll', { reroll_index: rerollIndex, reroll_intent: 'another_dish' })
    }
    track('decide_roll', {
      reroll_index: rerollIndex,
      exclude_count: state.excluded.length,
      utterance_used: utterance.length > 0,
      meal_slot: state.slot,
      intent,
    })

    set({ loading: true, error: '' })
    // 已定下的菜(picked)也要一起排除: 周末配菜要的是"再来一道别的",
    // 把刚定下的那道再推一遍就成了"今晚已定 2 道: A + A"
    const exclude = Array.from(new Set([...state.excluded, ...state.picked]))
    try {
      const result = (await decide({
        meal_slot: state.slot,
        exclude,
        utterance,
      })) as DecisionResultExt
      /**
       * 「服务端返回空」必须是一条**写出来**的分支。
       *
       * 以前它靠后面 `result.dish.name` 抛 TypeError 才落到 catch —— 那是 TypeError 的
       * 副产品, 不是契约的实现: 谁给那两行加个 `?.`(再正常不过的防御性改动), 空结果
       * 就会一路走到 `set({ result: null })`, 结果卡退回「饭决」空态, 不打角标、不报错、
       * 不打点。而"永远有答案"是我们对外最硬的一条承诺 —— 靠运气成立的承诺不算承诺。
       */
      if (!result?.dish) throw new Error('空结果')
      applyServerLayoutVersion(result.layout_version)
      set({
        result,
        loading: false,
        offline: false,
        round: state.round + 1,
        slot: result.meal_slot,
        resultShownAt: Date.now(),
      })
      // 在线结果也要进本地历史: 断网时才有得可查
      pushHistory(result)
      track('decide_result_shown', {
        decision_id: result.id || null,
        dish: result.dish.name,
        category: result.dish.category,
        main_ingredient: result.dish.main_ingredient,
        cook_minutes: result.dish.cook_minutes,
        relaxed: result.relaxed,
        relaxed_level: result.relaxed_level ?? null,
        candidate_count: result.candidate_count ?? null,
        source: result.source,
        meal_slot: result.meal_slot,
      })
      trackFilterTap(utterance, true)
      return result
    } catch (error) {
      /**
       * 离线兜底: 三条触发任一命中即切本地池 (PRD §7.6 时序图, 对两端硬性)
       *
       *   ① 断网              —— 秒级失败, 秒级切离线
       *   ② 服务端返回空/抛错  —— 上面那条显式 throw, 不是 TypeError 的副产品
       *   ③ 超时              —— `/decide` 单独设 2500ms (api/decide.ts), 不是全局 30 秒
       *
       * 三条都要在 3 秒内落到本地池并打「本地答案」角标: **"永远有答案"靠这一支兜住,
       * 不是靠主链路够快**。
       *
       * ⚠ 图上写的 `navigator.onLine` 主动判定, 代码里是 0 处 —— 当前兜底依赖"请求抛错"
       *   这条**被动**路径。本版不做(排 V1.3, PRD §7.6 已注明差异): 它影响的是"首屏是否
       *   预填", 不影响"永远有答案"这条承诺。
       */
      const outcome = decideOffline(
        {
          profile: readProfile() ?? {
            cuisines: [],
            spiceLevel: 2,
            avoid: [],
            cookCap: 60,
            mealBudget: null,
          },
          history: readHistory(),
          exclude,
        },
        new Date(),
      )
      if (!outcome) {
        set({ loading: false, error: (error as Error).message || '暂时没法决定，稍后再试' })
        trackFilterTap(utterance, false)
        return null
      }
      const result = toResult(outcome)
      set({
        result,
        loading: false,
        offline: true,
        round: state.round + 1,
        slot: outcome.mealSlot,
        resultShownAt: Date.now(),
      })
      pushHistory(result)
      track('decide_result_shown', {
        dish: result.dish.name,
        category: result.dish.category,
        main_ingredient: result.dish.main_ingredient,
        cook_minutes: result.dish.cook_minutes,
        relaxed: result.relaxed,
        relaxed_level: null,
        candidate_count: null,
        source: 'offline',
        meal_slot: result.meal_slot,
      })
      return result
    }
  },

  feedback: async (liked) => {
    const { result } = get()
    if (!result || !result.id) return
    try {
      await sendDecideFeedback(result.id, liked)
    } catch {
      // 反馈失败不影响用户继续用, 静默即可
    }
  },

  /**
   * 改 utterance。解析结果由调用方(UtteranceInput)传入:
   * understood=false 时传 null, 前端于是不回显任何东西, 也不改主按钮文案 ——
   * 没听懂就当没听见, 比猜错之后再改用户的菜要好。
   */
  setUtterance: (text, intent = null) => set({ utterance: text, intent }),

  /** 「就这个」: 除了打点, 还要真的记一次 accepted, 否则采纳率永远是 NULL */
  accept: () => {
    const { result, round, resultShownAt } = get()
    if (!result) return
    track('decide_accept', {
      decision_id: result.id || null,
      dish: result.dish.name,
      reroll_index: round,
      result_age_ms: resultShownAt ? Date.now() - resultShownAt : null,
      utterance_used: get().utterance.trim().length > 0,
    })
    void get().feedback(true)
  },

  viewSteps: () => {
    const { result } = get()
    if (!result) return
    track('decide_view_steps', {
      decision_id: result.id || null,
      dish: result.dish.name,
      steps: result.dish.steps.length,
    })
  },

  cookStart: () => {
    const { result } = get()
    if (!result) return
    track('decide_cook_start', { decision_id: result.id || null, dish: result.dish.name })
  },

  /**
   * 「做完了」: 按这次决策的结果菜谱扣减冰箱库存 (2.7.0 的 POST /decide/{id}/cook)
   *
   * 以前这里只打点 —— 当时的后端确实没有"按决策写 consumption_record"的接口,
   * 而做一个假的"已扣库存"提示是在骗用户, 所以扣库存只能走次屏「今晚这一餐」
   * (那是周菜单 MenuItem 维度, 和今日决策不是一回事)。现在接口已上线且幂等,
   * 这才是今日线该走的唯一入口。
   *
   * 失败一律不抛: "这顿做完了"是用户的事实, 扣库存只是它附带的动作 ——
   * 扣不到要如实降级(kind: 'failed'), 不能把主流程挡住。
   */
  cookDone: async () => {
    const { result } = get()
    if (!result) return { kind: 'none' }
    track('decide_cook_done', { decision_id: result.id || null, dish: result.dish.name })
    void get().feedback(true)

    // 离线兜底出的结果在服务端没有 decision_log, 拿不到 id 就没有可扣的对象
    if (!result.id) return { kind: 'skipped' }

    try {
      const ack = await cookDecision(result.id)
      if (ack.no_recipe) return { kind: 'no_recipe' }
      if (ack.already_cooked) return { kind: 'already' }
      return {
        kind: 'done',
        consumed: ack.consumed ?? [],
        missing: ack.missing ?? [],
      }
    } catch {
      return { kind: 'failed' }
    }
  },

  /** 倔强提示弹出: 一次会话只弹一次, 所以这里顺手把 shown 置上 */
  noteStubbornShown: (date = new Date()) => {
    if (get().stubbornShown) return
    set({ stubbornShown: true })
    track('stubborn_shown', {
      bucket: contextBucket(date),
      threshold: stubbornAfter(date),
      round: get().round,
    })
  },

  reset: () =>
    set({
      result: null,
      round: 0,
      stubbornShown: false,
      error: '',
      offline: false,
      utterance: '',
      intent: null,
      excluded: [],
      picked: [],
      resultShownAt: 0,
    }),
}))

/**
 * 把当前菜记进"不再回来"的名单。
 *
 * `another_dish`(周末配菜)只进 picked, 不进 excluded:
 *   她不是在换掉这道菜, 是在配一桌菜 —— 记进"已排除"等于把刚定下的一道说成
 *   "被淘汰的"(PRD R-12 ③ 明文要求)。不重复推荐由 roll() 负责:
 *   请求时把 picked 一起当 exclude 传, 但"已排除 N 道"这个数只数真正换掉的。
 */
export function markCurrentExcluded(intent: RollIntent): void {
  const { result, excluded, picked } = useDecideStore.getState()
  if (!result) return
  const name = result.dish.name
  if (intent === 'another_dish') {
    useDecideStore.setState({ picked: picked.includes(name) ? picked : [...picked, name] })
    return
  }
  useDecideStore.setState({
    excluded: excluded.includes(name) ? excluded : [...excluded, name],
  })
}

/**
 * 条件入口的点按。
 *
 * 原计划这里是 J6/J7 的采集点, 但新首页按设计**没有筛选格子** —— 首屏只做一件事,
 * 摆一排 chip 就等于把选择还给用户。所以 J6/J7 已作废, 判据换成后端
 * decision_log.candidate_count, 不再依赖这个事件。
 *
 * 这里保留打点只为兼容存量看板, **不得作为任何指标的数据源**(PRD v1.6)。
 * 别再给它找第二个触发点 —— 找不到不是没找全, 是首页本来就没有筛选这回事。
 */
function trackFilterTap(utterance: string, gotResult: boolean): void {
  if (!utterance) return
  track('home_filter_tap', {
    filter: 'utterance',
    value: utterance,
    result_count: gotResult ? 1 : 0,
  })
}

/** 记入本地历史 (离线去重的数据源), 只留最近 30 条 */
function pushHistory(result: DecisionResult) {
  try {
    const next: DecideHistoryItem[] = [
      {
        name: result.dish.name,
        category: result.dish.category,
        cuisine: result.dish.cuisine,
        main: result.dish.main_ingredient,
        date: toDateKey(new Date()),
      },
      ...readHistory(),
    ].slice(0, 30)
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  } catch {
    // 存不下就算了
  }
}

/** 连续决策到分档阈值 -> 该弹倔强提示了 (深夜 2 / 工作日 3 / 周末 5) */
export function shouldShowStubborn(round: number, shown: boolean, date: Date = new Date()): boolean {
  return !shown && round >= stubbornAfter(date)
}

export { stubbornAfter }
