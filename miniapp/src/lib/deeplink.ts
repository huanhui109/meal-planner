/**
 * 补单跳转 - 有配置小程序 AppID 就直接跳, 没有就降级为"复制清单 + 提示搜索"
 *
 * 为什么不做商品匹配: 本期不接采集, 也就不知道缺口食材对应哪个商品。
 * 与其编一个假的商品链接, 不如把"该买什么"原样交给用户, 让他自己在
 * 小象超市里搜 —— 这是诚实且真的能用的降级路径。
 */
import Taro from '@tarojs/taro'

export interface DeeplinkTarget {
  miniappAppId?: string | null
  link?: string | null
  /** 没有 AppID 时复制给用户的文本 */
  copyText: string
  platformLabel?: string
}

export async function openPurchaseLink(target: DeeplinkTarget): Promise<void> {
  const { miniappAppId, link, copyText, platformLabel = '小象超市' } = target

  if (miniappAppId) {
    try {
      await Taro.navigateToMiniProgram({ appId: miniappAppId, path: 'pages/index/index' })
      return
    } catch {
      // 没在 app.json 的 navigateToMiniProgramAppIdList 里时会失败, 继续走复制
    }
  }

  if (link) {
    try {
      await Taro.setClipboardData({ data: link })
      Taro.showToast({ title: '链接已复制, 去浏览器打开', icon: 'none', duration: 2400 })
      return
    } catch {
      // 忽略, 走下面的清单复制
    }
  }

  await Taro.setClipboardData({ data: copyText })
  Taro.showModal({
    title: `去${platformLabel}下单`,
    content: '清单已复制, 打开小象超市搜索粘贴即可。',
    showCancel: false,
    confirmText: '知道了',
  })
}

/** 把缺口拼成一段能直接粘贴到搜索框的文本 */
export function missingText(items: Array<{ name: string; quantity: number | null; unit: string }>): string {
  return items
    .map((item) => (item.quantity == null ? item.name : `${item.name} ${item.quantity}${item.unit}`))
    .join('、')
}
