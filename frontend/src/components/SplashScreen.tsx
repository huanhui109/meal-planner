/**
 * 品牌启动页 (需求 2) —— 参考 Apple 开机动画
 *
 * 分镜 (总时长 ~1600ms):
 *   0-120ms    纯底, Logo opacity 0 / scale 0.86
 *   120-780ms  Logo scale → 1, opacity → 1, 缓动 ease-out-quint
 *   700-1180ms Slogan 字距 0.5em → 0.06em + opacity → 1
 *   1300-1600ms 整体淡出
 *
 * 两个细节容易踩:
 *   1. 每次冷启动只播一次 —— 用 sessionStorage, 刷新页面不重播, 否则会烦
 *   2. prefers-reduced-motion 时压到 300ms 纯淡入 —— 动效是加分项不是门槛
 */
import React, { useEffect, useState } from 'react'
import { LogoMark } from './ui/logo'
import { brand } from '@shared/brand'

const PLAYED_KEY = 'meal-planner:splash-played'
const DURATION = 1600
/** reduced-motion 下只留一个极短的淡入, 不做缩放 */
const REDUCED_DURATION = 300

export const SplashScreen: React.FC = () => {
  const [visible, setVisible] = useState(false)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    let played = false
    try {
      played = sessionStorage.getItem(PLAYED_KEY) === '1'
    } catch {
      played = false
    }
    if (played) return

    const reduce =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const total = reduce ? REDUCED_DURATION : DURATION

    setVisible(true)
    const outTimer = window.setTimeout(() => setLeaving(true), total - 300)
    const endTimer = window.setTimeout(() => {
      setVisible(false)
      try {
        sessionStorage.setItem(PLAYED_KEY, '1')
      } catch {
        // 存不下就每次都播, 不影响功能
      }
    }, total)
    return () => {
      window.clearTimeout(outTimer)
      window.clearTimeout(endTimer)
    }
  }, [])

  if (!visible) return null

  return (
    <div className={`splash ${leaving ? 'is-leaving' : ''}`} role="presentation">
      <div className="splash-stage">
        <div className="splash-logo">
          <LogoMark size={104} />
        </div>
        <div className="splash-wordmark">{brand.name}</div>
        <div className="splash-slogan">{brand.slogan}</div>
      </div>
    </div>
  )
}

export default SplashScreen
