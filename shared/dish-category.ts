/**
 * 菜品类别法典 —— 两端唯一真源
 *
 * 为什么另立一部法典而不是复用 recipe.cuisine:
 *   导入时列错位, recipe.cuisine 装的是「荤菜/主食/早餐/甜品/调味品」这类源分类,
 *   396 道菜里没有任何一个菜系值。项目为此把 score_cuisine 全局钉成 0。
 *   现在需要的是**互斥的大类**(中餐/西餐/日韩/东南亚·南亚/其他), 与「品类」
 *   (荤菜/素菜/主食, 同品类打散用)也不是一个维度, 不能混用。
 *
 * 为什么类别要互斥且单值:
 *   同一份出餐方案里所有菜品必须同类, 尤其禁止中餐与西餐同桌。多值标签
 *   (cuisines 数组)做不到「只归属一个」, 所以 recipe 上是单列 + 单一 code。
 *
 * 与数据库的关系:
 *   迁移 0027 建 dish_category 字典表, 把这 5 行写进去, 便于运维改名称/
 *   排序/停用; recipe.dish_category_code 存这里的 code。服务端规则与校验
 *   只读本文件的同名常量(Python 侧镜像在 services/dish_rules.py), 由
 *   backend/tests/unit/test_dish_category_parity.py 静态比对两端一致。
 *   运行时不查字典表 —— 测试夹具会 TRUNCATE 所有表, 配置数据不该成为运行时依赖。
 *
 * 空值语义: null / '' = 用户没限定类别(不限), 但**方案内类别一致仍是硬规则**,
 * 不限不等于允许混搭。
 */

export type DishCategoryCode =
  | 'chinese'
  | 'western'
  | 'japanese_korean'
  | 'southeast_asian'
  | 'other'

export interface DishCategorySpec {
  code: DishCategoryCode
  label: string
  description: string
  sort_order: number
}

/** ⚠ 顺序即展示顺序; 增删类别必须同步 migration 0027 的种子行与 Python 常量, parity 测试会拦 */
export const DISH_CATEGORIES: DishCategorySpec[] = [
  { code: 'chinese', label: '中餐', description: '中式家常、川湘粤鲁等地方菜与中式主食', sort_order: 1 },
  { code: 'western', label: '西餐', description: '欧美菜式、烘焙、沙拉与西式主食', sort_order: 2 },
  { code: 'japanese_korean', label: '日韩', description: '日式与韩式料理', sort_order: 3 },
  { code: 'southeast_asian', label: '东南亚·南亚', description: '泰越新马印尼与印度等南亚料理', sort_order: 4 },
  { code: 'other', label: '其他', description: '融合菜、饮品甜品与暂未归类的条目', sort_order: 5 },
]

export const DISH_CATEGORY_CODES: DishCategoryCode[] = DISH_CATEGORIES.map((item) => item.code)

export const DISH_CATEGORY_LABELS: Record<DishCategoryCode, string> = Object.fromEntries(
  DISH_CATEGORIES.map((item) => [item.code, item.label]),
) as Record<DishCategoryCode, string>

/** 新菜未经回填时的兜底类别; 不是「人工归类为其他」的标记 */
export const DISH_CATEGORY_OTHER: DishCategoryCode = 'other'

export const isDishCategoryCode = (value: unknown): value is DishCategoryCode =>
  typeof value === 'string' && (DISH_CATEGORY_CODES as string[]).includes(value)

export type DishCategoryMix = 'none' | 'mixed' | 'chinese_western'

/**
 * 只做结构判定, 不生成中文文案 —— 错误文案由服务端 problem(422, ...) 单一给出,
 * 前端原样展示, 避免两处翻译漂移。
 */
export const detectDishCategoryMix = (
  codes: (string | null | undefined)[],
): DishCategoryMix => {
  const unique = new Set(codes.filter((code): code is string => Boolean(code)))
  if (unique.size <= 1) return 'none'
  return unique.has('chinese') && unique.has('western') ? 'chinese_western' : 'mixed'
}

export const dishCategoryLabel = (code: string | null | undefined): string =>
  (code && DISH_CATEGORY_LABELS[code as DishCategoryCode]) || '未分类'
