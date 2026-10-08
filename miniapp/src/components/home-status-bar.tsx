/**
 * 首页状态行 —— 替代原来的问候语
 *
 * 原来那行是「晚上好, 小明」+「9月23日 周二 · 工作日」, 占两行, 但对决策的
 * 信息量只有"晚餐"两个字。压成一行「19:20 · 晚餐 · 家里有 6 样 · 清淡少辣」,
 * 同高度多给两个有效信息, 并且把"时间锚点"显性化 —— 用户需要一眼确认你没把他的
 * 晚饭当夜宵。
 *
 * 餐次**不给用户选**, 由钟点推断(shared/decide.ts 的 resolveMealSlot):
 * 没有人会打开小程序想"我现在是晚餐还是夜宵", 他 100% 知道。摆一个选择器
 * 就是把已经知道的事又问一遍 —— 那等于让他填表单。
 */
import { Text, View } from '@tarojs/components'

import { MEAL_SLOT_LABELS } from '@shared/decide'
import { statusLine } from '@shared/decide-context'

export function HomeStatusBar({
  fridgeCount,
  now,
  tasteLabel,
}: {
  fridgeCount: number | null
  now?: Date
  /** 口味标签 (Demo status-line 的最后一段): 如「清淡 · 微辣」, 没填偏好则不渲染 */
  tasteLabel?: string | null
}) {
  const base = statusLine({
    date: now,
    fridgeCount,
    mealSlotLabel: (slot) => MEAL_SLOT_LABELS[slot] ?? '',
  })
  return (
    <View className="d-status-line">
      {/* now 可注入: 深夜/周末的文案没人会真的等到那个点去点一遍验证 */}
      <Text>{tasteLabel ? `${base} · ${tasteLabel}` : base}</Text>
    </View>
  )
}

export default HomeStatusBar
