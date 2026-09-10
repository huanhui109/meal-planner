import apiClient, { unwrap } from './client'
import type { OrderSuggestion, TodayOverview } from '../types'

/** 今日页一次拿全: 餐次 + 预算 + 采购缺口 + 补单建议 + 自做/外卖 + 时间线 */
export const getToday = () => unwrap<TodayOverview>(apiClient.get('/today'))

/** 在卡片上改了外卖参考价 -> 静默写回, 下次默认用它 */
export const rememberTakeoutPrice = (price: number) =>
  unwrap<{ takeout_reference_price: number }>(
    apiClient.post('/today/takeout-price', { price }),
  )

/** 补单建议 (采购页复用同一份计算) */
export const getOrderSuggestion = (menuId: number) =>
  unwrap<OrderSuggestion>(apiClient.get(`/menus/${menuId}/order-suggestion`))
