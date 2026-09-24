/**
 * 饭决 · 极简决策旗舰页（小程序）
 *
 * 只保留「今天吃啥」一件事: 复用现有 DecideBoard（与 H5 同款克制风格，
 * 单 CTA + 结果卡 + 换一个/就这个）。不挂预算/周菜单/时间线等 today 页的
 * 附加信息 —— 把主张收敛到「别选了，按一下」。
 *
 * 决策逻辑、离线同构、持久化全部走 lib/decide + 后端 /api/decide，不重写。
 */
import { useDidShow } from '@tarojs/taro'
import { View } from '@tarojs/components'

import { ensureLogin } from '../../lib/nav'
import { useThemeClass } from '../../lib/theme'
import DecideBoard from '../../components/decide-board'
import './index.scss'

export default function FandecidePage() {
  const themeClass = useThemeClass()

  // 进页即确保登录（未登录会跳登录态），与 today 页同款门禁
  useDidShow(() => {
    ensureLogin()
  })

  return (
    <View className={`page ${themeClass}`}>
      <View className="fd-stage">
        <DecideBoard />
      </View>
    </View>
  )
}
