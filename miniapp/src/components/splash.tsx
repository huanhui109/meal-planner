/**
 * 品牌启动页 (小程序) —— 需求 2, 与 H5 的 components/SplashScreen.tsx 同款动效
 *
 * 用**覆盖层**而不是新增启动页路由:
 *   app.config.ts 的 entryPagePath 必须保持 today —— 之前把 onboarding 排在第一位,
 *   导致老用户每次冷启动都重走一遍引导。这个坑不能再踩第二次。
 *
 * 冷启动只播一次靠模块级变量: 小程序的 JS 上下文在冷启动时重建,
 * 所以模块变量天然就是"每次启动一次"的语义, 不需要 storage。
 */
import { useEffect, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { brand } from '@shared/brand'
import { LogoMark } from './logo'

const DURATION = 1600
const REDUCED_DURATION = 300
/** 预留开关: 若将来接入无障碍设置, 置 true 即压到纯淡入 */
const REDUCED_DURATION_SKIP = false

/** 模块级: 一个启动周期内只播一次 */
let played = false

export function Splash() {
  const [visible, setVisible] = useState(false)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    if (played) return
    played = true

    // 小程序拿不到 prefers-reduced-motion (没有 matchMedia, getSystemInfoSync 也不暴露),
    // 所以这里不做降级。动效只有 1.6s 且不阻塞交互, 影响可控。
    const total = REDUCED_DURATION_SKIP ? REDUCED_DURATION : DURATION

    setVisible(true)
    const outTimer = setTimeout(() => setLeaving(true), total - 300)
    const endTimer = setTimeout(() => setVisible(false), total)
    return () => {
      clearTimeout(outTimer)
      clearTimeout(endTimer)
    }
  }, [])

  if (!visible) return null

  return (
    <View className={`splash ${leaving ? 'is-leaving' : ''}`}>
      <View className="splash__stage">
        <View className="splash__logo">
          <LogoMark size={96} />
        </View>
        <Text className="splash__wordmark">{brand.name}</Text>
        <Text className="splash__slogan">{brand.slogan}</Text>
      </View>
    </View>
  )
}

export default Splash
