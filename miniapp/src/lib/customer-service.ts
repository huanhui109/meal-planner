/**
 * 客服入口 (小程序) - 包装 Taro.openCustomerServiceChat
 *
 * 行为契约:
 * 1. 优先调起原生客服窗口 (微信后台已绑定客服微信号时)
 * 2. 调起失败 (未配置 corpId / 基础库过低 / 任何异常) → fallback 由调用方处理
 *    实践中 "未配置客服" 是常态, 由调用方弹 toast 或反馈 sheet 最自然
 */
import Taro from '@tarojs/taro'

export type CustomerServiceFallback = () => void | Promise<unknown>

export async function openCustomerServiceChat(
  fallback?: CustomerServiceFallback,
): Promise<boolean> {
  if (!Taro.openCustomerServiceChat) {
    await fallback?.()
    return false
  }
  try {
    await Taro.openCustomerServiceChat({ extInfo: { url: '' }, corpId: '' })
    return true
  } catch {
    await fallback?.()
    return false
  }
}
