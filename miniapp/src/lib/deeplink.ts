/**
 * 补单跳转 - 三级降级链: 1) 配置了 AppID 走 navigateToMiniProgram
 *                    2) 有外链走 setClipboardData
 *                    3) 兜底: 复制清单 + 提示去平台搜索
 *
 * 为什么三级降级:
 *   - 二期 (V3.0) 才接小象超市商品库, 现在 `data.order.miniapp_app_id` 永远空,
 *     100% 走兜底, 直白告诉用户"复制清单后去小象超市搜"是诚实且真的能用。
 *   - 旧版文案 "立即下单" 容易让用户以为跳到了小象超市, 实际只是复制了一段
 *     文字 —— 期望与现实不一致会引发"小程序坏了"的认知 (audit B2)。
 *
 * 注意: `navigateToMiniProgram` 失败常见原因不是用户拒绝, 是开发者没在
 * `app.json` 的 `navigateToMiniProgramAppIdList` 里登记目标 appid。这种情况
 * 给具体提示, 避免开发期踩坑。
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
      // 失败时明确告诉用户原因, 不静默吞掉
      Taro.showModal({
        title: '跳转失败',
        content: `未在 app.json 的 navigateToMiniProgramAppIdList 里登记「${miniappAppId}」, 改为复制清单。`,
        showCancel: false,
        confirmText: '知道了',
      })
      // 继续走下面的复制降级
    }
  }

  if (link) {
    try {
      await Taro.setClipboardData({ data: link })
      Taro.showToast({ title: '链接已复制, 去浏览器打开', icon: 'none', duration: 2400 })
      return
    } catch {
      // 走下面的清单复制
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
