#!/usr/bin/env node
/**
 * 饭决本地候选池生成器
 *
 * 单一真源 data/local_dish_pool.json  →  三端产物:
 *   backend/app/data/local_pool.py      Python 常量 (全字段名, 服务端决策用)
 *   shared/local-pool.generated.ts      H5 + 小程序共用 (短字段名, 压小程序包体积)
 *
 * 为什么要生成而不是手写三份: 「永远有答案」依赖离线池与服务端池 **内容完全一致**。
 * 手写两份必然漂移 —— 用户在断网时看到的菜和联网时不一样, 是最难排查的一类 bug。
 *
 * 用法:
 *   node scripts/gen_local_pool.mjs           写入产物
 *   node scripts/gen_local_pool.mjs --check    只校验产物是否最新 (CI 用, 不一致退出码 1)
 *
 * 校验规则 (不满足直接报错, 不生成):
 *   - 菜名唯一
 *   - 极简做法 3-5 步, 每步 <=20 字 (需求 10)
 *   - 品类必须是有限枚举 (「同品类打散」依赖它)
 *   - 辣度 0-4
 *   - slots 只能是 null (不限制) 或非空餐次子集, 缺字段报错
 *   - 深夜候选 (light=true 且 minutes<=20) 不少于 10 道, 否则深夜场景会没得选
 *   - 菜名不能像"不是一个菜" (调料的闸见 NON_DISH_SUFFIXES / NON_DISH_WORDS)
 */

/**
 * 生成期防线: 离线池里不许出现"不是一个菜"的条目。
 *
 * 为什么离线池也要管: 断网时客户端是**只**靠这份数据出结果的, 服务端那道
 * is_dish 过滤完全够不着。2026-09-23 事故的教训是——只要入口没堵住, 用户就真的
 * 能在结果卡上看见"冰粉"(它命中的是后缀档词条, 这道绊线真拦得住)。
 *
 * 为什么这里写得比服务端粗: 服务端负责判定(权威清单在 backend/app/services/
 * dish_rules.py, 新增 recipe 走那里), 这里只负责在人工往 data/local_dish_pool.json
 * 里加条目的那一刻报错。判定口径放两处必然漂移, 所以这里是**粗筛的绊线**而不是
 * 第二套规则: 只收那些几乎不可能出现在正经菜名里的词。
 */
// ⚠️ 补词前先读这一段: 只收"几乎不可能嵌进正经菜名"的词, 优先收尾部词。
// trap = 一旦把左边的词收进这张表, 右边那道正经菜就会被踢出离线池
//   葱油       → 葱油拌面
//   番茄       → 番茄炒蛋、番茄意面（而"番茄红酱"确实是非菜, 一词两命, 收不得）
//   冬瓜       → 冬瓜排骨汤（而"冬瓜茶"确实是非菜）
//   糖醋       → 糖醋排骨（而"糖醋汁"确实是非菜）
// 为什么这条禁令比服务端那边更严: 服务端漏判了能立刻回滚, 离线池判错了要等用户
// 断网才复现, 而且服务端日志里一片空白 —— 它是两处里容错空间更小的那一处。
// 权威性不在这里: 真正的判定在 backend/app/services/dish_rules.py 的 guess_is_dish(),
// 它的匹配方式有整名相等 / 结尾 / 子串三类, 另外还有一层源分类。本注释只描述
// 结构、不描述数量 —— 具体名单与层数一律以 guess_is_dish() 的当前实现为准,
// 它改了这里就要跟着改, 否则两边静默分叉(而且分叉只在断网时才看得出来)。
// 补词前先拿这个词去可用候选里搜一遍, 有命中就别收。
// 下面两张表与真源同名两档对齐各自的匹配方式: NON_DISH_SUFFIXES 是"结尾即定性",
// NON_DISH_WORDS 是"出现在任意位置即定性"。早先这里是一张表 + includes 通吃, 于是
// 「汤/酱/油」这类短词一旦补进来就会误杀正经菜(酱牛肉/葱油拌面), 补词的人只能不补
// —— 表就废了。拆开之后, 后缀档能放心收尾部词, 子串档只留给确实需要通吃的词。
// ⚠️ 这两张表是**离线池用的子集**, 不是 dish_rules.py 的镜像: 那边后缀档 22 词、子串档
// 9 词, 这里是 20 + 4。差出来的那些没核过是有意还是漏的 —— 少收了 雪花酥/饼干/蛋挞/辣子
// (其中缺"辣子", 意味着连本文件开头拿来举例的「油泼辣子」都拦不住), 子串档也没收
// 汤力/菲士/拉西/啤酒桶/可乐桶; 反过来这里多带了 龟苓膏/蘸料。补词前先确认离线池现有
// 条目里有没有命中, 别照着服务端那份整抄 —— 要对齐的是"不误杀", 不是名单长度。
const NON_DISH_SUFFIXES = [
  // 甜品
  '冰淇淋', '雪媚娘', '奶冻', '司康', '布丁', '龟苓膏',
  // 饮品
  '奶茶', '柠檬水', '气泡水', '苏打水', '奶昔', '果昔', '冰沙', '冰茶', '冰粉',
  // 调味品
  '酱料', '蘸料', '底料', '糖色', '糖浆',
]

// 为什么这四个不能改成后缀匹配: 真源的事故名单里就有「酸梅汤（半成品加工）」这种
// 带尾巴的写法, endsWith('酸梅汤') 判不到它。按后缀判等于把这一档悄悄放过去,
// 而它恰恰是 2026-09-23 事故里被点名的条目。
const NON_DISH_WORDS = [
  // 酒水/快餐半成品
  '莫吉托', '鸡尾酒', '轰炸机', '酸梅汤',
]
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SOURCE = path.join(ROOT, 'data/local_dish_pool.json')
const TARGETS = [
  path.join(ROOT, 'backend/app/data/local_pool.py'),
  path.join(ROOT, 'shared/local-pool.generated.ts'),
]

/** 品类枚举 —— 「同品类打散」的计算粒度, 加新品类必须同步改 SHORT.c 的注释 */
const CATEGORIES = ['荤菜', '素菜', '汤羹', '主食', '面食', '凉菜']

/** 餐次枚举 —— 与后端 MealSlot.ALL 一致, slots 里的值必须是它的子集 */
const MEAL_SLOTS = ['breakfast', 'lunch', 'dinner', 'late_night']

/** 全键 → 短键映射 (只在 TS 产物里用短键) */
const SHORT = {
  name: 'n',
  cuisine: 'cu',
  category: 'ca',
  main: 'mi',
  minutes: 'cm',
  calories: 'kcal',
  difficulty: 'df',
  spice: 'sp',
  light: 'lt',
  slots: 'ms',
  cover: 'cv',
  tags: 'tg',
  flavors: 'ft',
  ingredients: 'ig',
  steps: 'st',
}

/**
 * JSON 源文件允许写 # 注释 (纯 JSON 不支持), 生成时剥掉。
 * 没有这个的话, 这份数据的字段口径就只能写在 README 里, 改数据的人看不到。
 */
function loadSource() {
  const raw = readFileSync(SOURCE, 'utf8')
  const stripped = raw
    .split('\n')
    .filter((line) => !line.trimStart().startsWith('#'))
    .join('\n')
  return JSON.parse(stripped)
}

function validate(dishes) {
  const errors = []
  const seen = new Set()

  for (const d of dishes) {
    const tag = `「${d.name}」`
    if (seen.has(d.name)) errors.push(`${tag} 菜名重复`)
    seen.add(d.name)

    if (!CATEGORIES.includes(d.category)) {
      errors.push(`${tag} 品类 ${d.category} 不在枚举内: ${CATEGORIES.join('/')}`)
    }
    if (!(d.spice >= 0 && d.spice <= 4)) errors.push(`${tag} 辣度 ${d.spice} 超出 0-4`)
    // slots 错了是"悄悄改分数": 填错值的菜会在某一餐被凭空加分, 比留空难查得多
    if (d.slots === undefined) {
      errors.push(`${tag} 缺 slots: 库里没标这道菜的 meal_slots 就显式写 null`)
    } else if (d.slots !== null) {
      const bad = (Array.isArray(d.slots) ? d.slots : []).filter((s) => !MEAL_SLOTS.includes(s))
      if (!Array.isArray(d.slots) || !d.slots.length || bad.length) {
        errors.push(`${tag} slots 只能是 null 或非空的餐次子集: ${JSON.stringify(d.slots)}`)
      }
    }
    if (!Array.isArray(d.steps) || d.steps.length < 3 || d.steps.length > 5) {
      errors.push(`${tag} 极简做法要 3-5 步, 现在是 ${d.steps ? d.steps.length : 0} 步`)
    } else {
      d.steps.forEach((s, i) => {
        if (s.length > 20) errors.push(`${tag} 第 ${i + 1} 步 ${s.length} 字, 超过 20 字上限`)
      })
    }
    if (!d.main) errors.push(`${tag} 缺主料, 「连续两餐不重样」没法算`)

    // 判据必须与 backend/app/services/dish_rules.py 的 guess_is_dish() 同口径:
    // 那边怎么匹配, 这里的同名名单就怎么匹配 —— 后缀档用 endsWith, 子串档用 includes。
    // guess_is_dish() 改了匹配方式, 这里要跟着改, 否则两边会静默分叉:
    // 同一个词表在一处杀、另一处放, 而分叉只在断网时才看得出来。
    const suffix = NON_DISH_SUFFIXES.find((w) => d.name.endsWith(w))
    const word = NON_DISH_WORDS.find((w) => d.name.includes(w))
    if (suffix) {
      // 措辞里写"结尾"而不是"包含": 报错时得让人一眼看出是哪一档命中
      errors.push(`${tag} 菜名以非菜绊线词「${suffix}」结尾: 调味品/饮品/甜品不进离线池`)
    }
    if (word) {
      errors.push(`${tag} 菜名含非菜绊线词「${word}」: 调味品/饮品/甜品不进离线池`)
    }
  }

  const lateNight = dishes.filter((d) => d.light && d.minutes <= 20)
  if (lateNight.length < 10) {
    errors.push(`深夜候选只 ${lateNight.length} 道 (要 >=10), 深夜场景会没得选`)
  }

  if (errors.length) {
    console.error('候选池校验失败:')
    for (const e of errors) console.error('  ✗ ' + e)
    process.exit(1)
  }
  return { lateNight: lateNight.length }
}

const py = (v) => {
  if (v === null || v === undefined) return 'None'
  if (typeof v === 'boolean') return v ? 'True' : 'False'
  if (typeof v === 'number') return String(v)
  return JSON.stringify(v)
}

function renderPython(dishes, stats) {
  const rows = dishes
    .map((d) => {
      // 字段顺序对齐数据模型, 方便人工 diff
      return [
        '    {',
        `        "name": ${py(d.name)},`,
        `        "cuisine": ${py(d.cuisine)},`,
        `        "category": ${py(d.category)},`,
        `        "main": ${py(d.main)},`,
        `        "minutes": ${d.minutes},`,
        `        "calories": ${d.calories},`,
        `        "difficulty": ${d.difficulty},`,
        `        "spice": ${d.spice},`,
        `        "light": ${py(d.light)},`,
        `        "slots": ${py(d.slots)},`,
        `        "cover": ${py(d.cover)},`,
        `        "tags": ${py(d.tags)},`,
        `        "flavors": ${py(d.flavors)},`,
        `        "ingredients": ${py(d.ingredients)},`,
        `        "steps": ${py(d.steps)},`,
        '    },',
      ].join('\n')
    })
    .join('\n')

  return `"""饭决本地候选池 - 由 scripts/gen_local_pool.mjs 生成, 请勿手改

数据源: data/local_dish_pool.json (共 ${dishes.length} 道, 其中深夜候选 ${stats.lateNight} 道)

用途:
1. 服务端 DecisionService 的候选来源之一 (库里菜谱不足时兜底)
2. 启动时若 recipe 表为空, 用于引导灌库

两个产物刻意用不同的字段名:
  Python 产物是全字段名 —— 服务端直接读, 字段顺序对齐数据模型便于人工 diff;
  TS 产物是 SHORT 映射的短键 —— 这份数据会打进小程序包, 体积敏感。
两边都由同一份 JSON 生成, 加字段必须改生成器再重跑, 否则产物会停在上一次的口径上
(slots 就是这么漏的: 只在一端加了字段, 另一端照旧拿到 None)。
"""
from __future__ import annotations

from typing import Any, Dict, List

LOCAL_DISHES: List[Dict[str, Any]] = [
${rows}
]
`
}

function renderTs(dishes, stats) {
  const rows = dishes
    .map((d) => {
      const parts = Object.entries(d)
        .map(([k, v]) => {
          const key = SHORT[k]
          if (!key) throw new Error(`字段 ${k} 没有短键映射`)
          return `${key}: ${JSON.stringify(v)}`
        })
        .join(', ')
      return `  { ${parts} },`
    })
    .join('\n')

  return `/**
 * 饭决本地候选池 - 由 scripts/gen_local_pool.mjs 生成, 请勿手改
 *
 * 数据源: data/local_dish_pool.json (共 ${dishes.length} 道, 深夜候选 ${stats.lateNight} 道)
 * 字段名是压缩过的短键 (n=菜名 / mi=主料 / lt=轻食 / st=步骤 ...), 全键见生成器里的 SHORT 映射。
 * 压短键是为了小程序包体积 —— 这份数据要打进客户端, 断网时靠它出结果。
 */
export interface LocalDish {
  /** 菜名 */
  n: string
  /** 菜系 */
  cu: string
  /** 品类 (同品类打散的粒度) */
  ca: string
  /** 主料 (连续两餐不重样的粒度) */
  mi: string
  /** 出餐分钟数 */
  cm: number
  /** 热量 kcal */
  kcal: number
  /** 难度 1-5 */
  df: number
  /** 辣度 0-4 */
  sp: number
  /** 轻食: 深夜只从这部分挑 */
  lt: boolean
  /** 适合餐次 (R-11 软加分): null = 不限制, 不是"哪顿都不合适" */
  ms: string[] | null
  /** 结果卡角标短文本 */
  cv: string
  /** 场景标签 */
  tg: string[]
  /** 味型标签 */
  ft: string[]
  /** 食材 */
  ig: string[]
  /** 极简做法 3-5 步 */
  st: string[]
}

export const LOCAL_DISHES: LocalDish[] = [
${rows}
]
`
}

function main() {
  const check = process.argv.includes('--check')
  const dishes = loadSource()
  const stats = validate(dishes)

  const rendered = [
    renderPython(dishes, stats),
    renderTs(dishes, stats),
  ]

  if (check) {
    let ok = true
    TARGETS.forEach((target, i) => {
      const current = readFileSync(target, 'utf8')
      if (current !== rendered[i]) {
        console.error(`✗ ${path.relative(ROOT, target)} 与数据源不一致, 请运行 make gen-pool`)
        ok = false
      } else {
        console.log(`✓ ${path.relative(ROOT, target)}`)
      }
    })
    process.exit(ok ? 0 : 1)
  }

  TARGETS.forEach((target, i) => {
    mkdirSync(path.dirname(target), { recursive: true })
    writeFileSync(target, rendered[i], 'utf8')
    console.log(`写入 ${path.relative(ROOT, target)}`)
  })
  console.log(`共 ${dishes.length} 道菜, 深夜候选 ${stats.lateNight} 道`)
}

main()
