/**
 * 「家里有啥」快选入口 (R-09)
 *
 * 为什么要有这个: fridge_inventory 表实测 0 行 —— 用户根本没有录入入口,
 * 于是"库存命中率"这个 25 分权重一直在空转。能力有(食材侧覆盖 94.2%), 数据空。
 *
 * 三条硬约束:
 *   1. **绝不阻塞决策。** 一个都不点, 直接回首屏按「饭决」, 成功率 100%。
 *      这是"它不是表单"的判别法 —— 首屏不能有任何"不处理就没法得到答案"的东西。
 *   2. **点一个存一个, 没有保存按钮。** 竞品要手输 10 样再点保存, 这里点一下就入库,
 *      带 3 秒 undo。这是"录入成本比竞品低一个数量级"的关键。
 *   3. **只放 12 个 chip。** 60 个是完整冰箱页的快选池规模; 首页超过 12 个
 *      就从"录入"变成"筛选器"了。
 *
 * 为什么放次屏不放首屏: 首屏只做一件事 —— 定这一顿。「家里有啥」是"做"这个模式的
 * 合法性证明, 但它出现在**决策之后**。放首屏就变成 SuperCook("先录食材"), 那是竞品
 * 明确"不抄"的对象。
 */
import React, { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { addInventoryItem, deleteInventoryItem } from '../api/inventory'
import { toastWithUndo } from '../lib/undo'
import { track } from '../lib/track'
import type { InventoryItem } from '../types'

/**
 * 12 个高频食材 —— 词表由 SQL 实跑确定, 不许拍脑袋写
 *
 * 实跑语句 (**注意必须 JOIN**: `recipe_ingredient` 表没有 `ingredient_name` 列,
 * 只有 `ingredient_id`。PRD 里那条 `SELECT ingredient_name ... FROM recipe_ingredient`
 * 直接跑会报 Unknown column, 真实列名在 `ingredient.name`):
 *
 *   SELECT i.name AS ingredient_name, COUNT(*) c
 *   FROM recipe_ingredient ri JOIN ingredient i ON i.id = ri.ingredient_id
 *   GROUP BY i.name ORDER BY c DESC;
 *
 * 定稿词表(取前 12 名, 剔除调味品与水):
 *   鸡蛋 75 · 洋葱 31 · 土豆 21 · 胡萝卜 18 · 青椒 17 · 五花肉 15
 *   面粉 15 · 牛奶 14 · 番茄 12 · 排骨 11 · 黄瓜 8 · 豆腐 7
 *
 * 这 12 味的覆盖率 —— **引用必须带分母**, 只写百分比会和验收口径对不上:
 *   175 / 373 = 46.9%   分母 = recipe 里有食材行的菜 (COUNT(DISTINCT recipe_id) FROM recipe_ingredient)
 *   159 / 342 = 46.5%   分母 = is_dish = 1 的菜
 * 两种口径都 ≥40%, R-09 验收⑥成立。
 * ⚠ 曾经被记成「179 道 ≈45%」: 179 是 `is_dish=1 AND category='荤菜'` 的条数,
 *   被误当成了候选池规模。写覆盖率之前先确认分母, 别再拿品类数当分母。
 *
 * 为什么必须剔调味品 —— **不只是"家家都有", 是勾了也不加分**:
 *   原始词频前 12 里有 9 个是调味料(生抽116 / 盐111 / 料酒68 / 白糖59 / 老抽59 /
 *   姜53 / 大蒜46 / 蚝油46 / 水40 / 葱39 / 酱油31 / 淀粉30 / 八角28 / 生姜26)。
 *   而打分侧 `_inventory_ratio()` 的 `staples` 白名单把调味料**排除在库存命中率之外**,
 *   也就是说用户勾了"有生抽", score_inventory 那 25 分一點都拿不到。
 *   勾了不加分还占一个 chip 位 = 这一行变成纯装饰。
 *
 * ⚠ 剔除标准是"是不是调味品", **不是"名字里带葱姜蒜"**:
 *   「洋葱」词频 31 排第二, 它是蔬菜不是调味品 —— 按"葱姜蒜"整类剔掉它, 和
 *   dish_rules.py 里"牛奶含『牛』判成荤菜"是同一类假阳性。
 *   「猪肉」只有 8 道且主料与「五花肉」15 道重合, 让位给洋葱。
 *
 * 🔴 洋葱的两个口径差 32 倍, 看错就会把它删掉(已经踩过一次):
 *   洋葱: 配料表含 32 道(真菜口径), main_ingredient 命中 0 道。
 *         ⚠ 看前者 —— 库存命中用的是 c.ingredients 全量, 不是 main_ingredient。
 *   对照: 土豆 main_ingredient = 8 道, 青椒 = 1 道。
 *
 *   打分侧算库存命中率的是 `_needed_ingredients(c)`(decision_service.py),
 *   取的是**全部非主食类食材**, 不是 main_ingredient 那一个字段; 而
 *   `Candidate.ingredients` 是从 recipe_ingredient 整表拉过来的。
 *   所以"家里有洋葱"能对 32 道菜产生 hits, 删掉它 = 白丢 32 道的库存信号,
 *   而 R-09 要的正是"用户录了要有反馈"。
 *
 * 🔴 西红柿 / 番茄 同物异名(本版不修, 必须显式记录, 不许让它变成静默的):
 *   「西红柿」9 道与「番茄」12 道是同一种东西的两个名字。chip 只叫「番茄」,
 *   菜谱里写「西红柿」的那些菜就匹配不上。
 *
 *   它的性质是**词面不匹配导致的信任缺口, 不是覆盖率缺口** —— 这 9 道里 7 道
 *   已经被其余 11 味覆盖, 净新增只有 2 道 / +0.5pt。按覆盖率算它排不进 V1.3,
 *   按信任算它必须排进去: 用户勾了「西红柿」、系统不认, 这一下比少两道菜伤得多。
 *   别把它归档成"+0.5pt 覆盖率", 那会在排期时被砍掉, 而且砍得看起来很合理。
 *
 *   V1.3 用别名表(shared/decide.ts 的 ALIAS_PAIRS 已有 西红柿→番茄)统一解决;
 *   本版不手工补第二个 chip, 因为 chip 行出现两个看着一样的按钮更伤。
 *
 * 数字是默认保质期(天): 快选行不暴露保质期输入, 按品类给默认值。
 */
const QUICK_CHIPS: Array<{ name: string; days: number }> = [
  { name: '鸡蛋', days: 15 },
  { name: '洋葱', days: 30 },
  { name: '土豆', days: 30 },
  { name: '胡萝卜', days: 14 },
  { name: '青椒', days: 5 },
  { name: '五花肉', days: 5 },
  { name: '面粉', days: 180 },
  { name: '牛奶', days: 7 },
  { name: '番茄', days: 5 },
  { name: '排骨', days: 5 },
  { name: '黄瓜', days: 5 },
  { name: '豆腐', days: 3 },
]

function expiryIso(days: number): string {
  const date = new Date(Date.now() + days * 86400000)
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

const FridgeQuickAdd: React.FC<{
  items: InventoryItem[]
  onChanged: () => void
}> = ({ items, onChanged }) => {
  const navigate = useNavigate()
  const [pending, setPending] = useState<string | null>(null)

  const owned = useMemo(() => new Set(items.map((item) => item.ingredient_name)), [items])
  const expiringCount = useMemo(() => items.filter((item) => item.expiring_soon).length, [items])
  const startedAt = React.useRef(Date.now())

  const add = async (name: string, days: number) => {
    if (pending || owned.has(name)) return
    setPending(name)
    try {
      const saved = await addInventoryItem({
        ingredient_name: name,
        quantity: 1,
        unit: '份',
        expiry_date: expiryIso(days),
      })
      onChanged()
      track('fridge_quickadd', {
        ingredient: name,
        // 新用户录完 3 样要 ≤30 秒 (R-09 ②), 用从进页面起的累计时长看 P75
        duration_ms: Date.now() - startedAt.current,
      })
      // 3 秒后悔窗口: 误点一个不该有那么高的代价
      toastWithUndo({
        key: `fridge-${saved.id}`,
        text: `${name} 已入冰箱`,
        seconds: 3,
        onUndo: async () => {
          await deleteInventoryItem(saved.id)
          onChanged()
        },
      })
    } catch {
      // 单个失败不弹错: 这条链路本来就是"顺手点一下", 弹错比不弹更打断
    } finally {
      setPending(null)
    }
  }

  const remove = async (item: InventoryItem) => {
    try {
      await deleteInventoryItem(item.id)
      onChanged()
    } catch {
      // 同上, 静默
    }
  }

  return (
    <div className="fridge-quick">
      <div className="fridge-quick-head">
        <span className="fridge-quick-title">
          {items.length > 0
            ? `家里有 ${items.length} 样${expiringCount > 0 ? ` · ${expiringCount} 样临期` : ''}`
            : '家里有啥？点一下，30 秒告诉我'}
        </span>
        {items.length > 0 ? (
          <button type="button" className="card-link" onClick={() => navigate('/inventory')}>
            改一下 →
          </button>
        ) : null}
      </div>

      {items.length > 0 ? (
        <div className="fridge-quick-chips">
          {items.slice(0, 12).map((item) => (
            <button
              key={item.id}
              type="button"
              className={`fridge-chip ${item.expiring_soon ? 'is-expiring' : ''}`}
              onClick={() => void remove(item)}
            >
              {item.ingredient_name} ×
            </button>
          ))}
        </div>
      ) : null}

      {/* 空态常驻: 无论有没有数据, 高频 chip 都在, 因为"再补一样"是高频动作 */}
      <div className="fridge-quick-chips">
        {QUICK_CHIPS.filter((chip) => !owned.has(chip.name)).map((chip) => (
          <button
            key={chip.name}
            type="button"
            className="fridge-chip is-add"
            disabled={pending != null}
            onClick={() => void add(chip.name, chip.days)}
          >
            {chip.name}
          </button>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="fridge-quick-note">一个都不点也能直接按饭决，不影响出菜。</div>
      ) : null}
    </div>
  )
}

export default FridgeQuickAdd
