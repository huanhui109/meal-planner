/**
 * 「家里有啥」快选入口 (R-09) 小程序端
 *
 * 为什么要有这个: fridge_inventory 表实测 0 行 —— 用户根本没有录入入口,
 * 于是"库存命中率"这个 25 分权重一直在空转。能力有(食材侧覆盖 94.2%), 数据空。
 *
 * 三条硬约束:
 *   1. **绝不阻塞决策。** 一个都不点, 直接回首屏按「饭决」, 成功率 100%。
 *      这是"它不是表单"的判别法 —— 首屏不能有任何"不处理就没法得到答案"的东西。
 *   2. **点一个存一个, 没有保存按钮。** 带 3 秒撤销。这是"录入成本比竞品低一个数量级"的关键。
 *   3. **只放 12 个 chip。** 60 个是完整冰箱页的快选池规模; 首页超过 12 个
 *      就从"录入"变成"筛选器"了。
 *
 * 为什么放次屏不放首屏: 首屏只做一件事 —— 定这一顿。「家里有啥」是"做"这个模式的
 * 合法性证明, 但它出现在**决策之后**。放首屏就变成 SuperCook("先录食材"), 那是竞品
 * 明确"不抄"的对象。
 */
import { useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import type { InventoryItem } from '@shared/types'

import { addInventory, deleteInventory } from '../lib/api'
import { track } from '../lib/track'

/**
 * 12 个高频食材 —— 词表由 SQL 实跑确定, 不许拍脑袋写
 *
 * 实跑语句 (**注意必须 JOIN**: `recipe_ingredient` 表没有 `ingredient_name` 列,
 * 只有 `ingredient_id`):
 *
 *   SELECT i.name AS ingredient_name, COUNT(*) c
 *   FROM recipe_ingredient ri JOIN ingredient i ON i.id = ri.ingredient_id
 *   GROUP BY i.name ORDER BY c DESC;
 *
 * 定稿词表(取前 12 名, 剔除调味品与水):
 *   鸡蛋 75 · 洋葱 31 · 土豆 21 · 胡萝卜 18 · 青椒 17 · 五花肉 15
 *   面粉 15 · 牛奶 14 · 番茄 12 · 排骨 11 · 黄瓜 8 · 豆腐 7
 *
 * 为什么必须剔调味品 —— **不只是"家家都有", 是勾了也不加分**:
 *   原始词频前 12 里有 9 个是调味料(生抽116 / 盐111 / 料酒68 ...), 而打分侧
 *   `_inventory_ratio()` 的 staples 白名单把调味料**排除在库存命中率之外**,
 *   用户勾了"有生抽", score_inventory 那 25 分一点都拿不到。
 *   勾了不加分还占一个 chip 位 = 这一行变成纯装饰。
 *
 * ⚠ 剔除标准是"是不是调味品", **不是"名字里带葱姜蒜"**:
 *   「洋葱」31 道排第二, 它是蔬菜不是调味品 —— 按类名整类剔掉它, 和
 *   dish_rules.py 里"牛奶含『牛』判成荤菜"是同一类假阳性。
 *
 * 🔴 已知覆盖缺口(本版不修, 必须显式记录, 不许让它变成静默的):
 *   「西红柿」9 道与「番茄」12 道是同一种东西的两个名字。chip 只叫「番茄」,
 *   菜谱里写「西红柿」的那些菜就匹配不上 —— 这 9 道菜的库存命中算不到。
 *   V1.3 用别名表(shared/decide.ts 的 ALIAS_PAIRS 已有 西红柿→番茄)统一解决;
 *   本版不手工补第二个 chip, 因为 chip 行出现两个看着一样的按钮,
 *   比少覆盖 9 道菜更伤。
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

/** 撤销窗口: 3 秒。误点一个不该有那么高的代价 */
const UNDO_MS = 3000

function expiryIso(days: number): string {
  const date = new Date(Date.now() + days * 86400000)
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

export function FridgeQuickAdd({
  items,
  onChanged,
}: {
  items: InventoryItem[]
  onChanged: () => void
}) {
  const [pending, setPending] = useState<string | null>(null)
  /** 3 秒可撤销: 微信没有带按钮的 toast, 这里用行内撤销条, 到点自动消失 */
  const [undo, setUndo] = useState<{ id: number; name: string } | null>(null)
  /** 进页面时刻: 用它看"录完 3 样要多久", 不能每次渲染都重取 */
  const startedAtRef = useRef(Date.now())

  const owned = new Set(items.map((item) => item.ingredient_name))
  const expiringCount = items.filter((item) => item.expiring_soon).length

  const add = async (name: string, days: number) => {
    if (pending || owned.has(name)) return
    setPending(name)
    try {
      const saved = await addInventory({
        ingredient_name: name,
        quantity: 1,
        unit: '份',
        expiry_date: expiryIso(days),
        source: 'quick',
      })
      onChanged()
      track('fridge_quickadd', {
        ingredient: name,
        // 新用户录完 3 样要 ≤30 秒 (R-09 ②), 用从进页面起的累计时长看 P75
        duration_ms: Date.now() - startedAtRef.current,
      })
      setUndo({ id: saved.id, name })
      setTimeout(() => setUndo(null), UNDO_MS)
    } catch {
      // 单个失败不弹错: 这条链路本来就是"顺手点一下", 弹错比不弹更打断
    } finally {
      setPending(null)
    }
  }

  const remove = async (item: InventoryItem) => {
    try {
      await deleteInventory(item.id)
      onChanged()
    } catch {
      // 同上, 静默
    }
  }

  const undoAdd = async () => {
    if (!undo) return
    const target = undo
    setUndo(null)
    try {
      await deleteInventory(target.id)
      onChanged()
    } catch {
      // 静默
    }
  }

  return (
    <View className="fridge-quick">
      <View className="fridge-quick__head">
        <Text className="fridge-quick__title">
          {items.length > 0
            ? `家里有 ${items.length} 样${expiringCount > 0 ? ` · ${expiringCount} 样临期` : ''}`
            : '家里有啥？点一下，30 秒告诉我'}
        </Text>
        {items.length > 0 ? (
          <Text className="fridge-quick__link" onClick={() => Taro.switchTab({ url: '/pages/fridge/index' })}>
            改一下 →
          </Text>
        ) : null}
      </View>

      {items.length > 0 ? (
        <View className="fridge-quick__chips">
          {items.slice(0, 12).map((item) => (
            <Text
              key={item.id}
              className={`fridge-chip${item.expiring_soon ? ' is-expiring' : ''}`}
              onClick={() => void remove(item)}
            >
              {item.ingredient_name} ×
            </Text>
          ))}
        </View>
      ) : null}

      {/* 空态常驻: 无论有没有数据, 高频 chip 都在, 因为"再补一样"是高频动作 */}
      <View className="fridge-quick__chips">
        {QUICK_CHIPS.filter((chip) => !owned.has(chip.name)).map((chip) => (
          <Text
            key={chip.name}
            className="fridge-chip is-add"
            onClick={() => void add(chip.name, chip.days)}
          >
            {chip.name}
          </Text>
        ))}
      </View>

      {undo ? (
        <View className="fridge-quick__undo">
          <Text className="fridge-quick__undo-text">{undo.name} 已入冰箱</Text>
          <Text className="fridge-quick__undo-btn" onClick={() => void undoAdd()}>
            撤销
          </Text>
        </View>
      ) : null}

      {items.length === 0 ? (
        <Text className="fridge-quick__note">一个都不点也能直接按饭决，不影响出菜。</Text>
      ) : null}
    </View>
  )
}

export default FridgeQuickAdd
