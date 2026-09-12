/**
 * 品牌标识
 *
 * 图标本体是 assets/logo/logo-mark.svg (由 scripts/gen_logo.mjs 生成),
 * 这里只负责尺寸与无障碍属性, 不在代码里重画一遍几何, 避免 Logo 走样。
 *
 * 主题跟随:
 *   - 默认根据 useThemeStore 切换 (亮色 UI 用 default = 深容框; 暗色 UI 用 inverse = 白容框)
 *   - 显式传 `inverse` 时强制 inverse, 优先级高于自动推断 (给硬性深色场景如启动封面/分享卡)
 *   - 显式传 `lightFrame` 强制 default, 用于亮色 UI 上的固定位置
 */
import React from 'react'
import { brand } from '@shared/index'
import { useThemeStore } from '../../stores/useThemeStore'

interface LogoMarkProps {
  /** 显示边长 (px) */
  size?: number
  /** 深色背景上换成白底反白版 */
  inverse?: boolean
  /** 强制使用亮色版 (深容框), 适用于亮色 UI 上的固定位置 */
  lightFrame?: boolean
  className?: string
}

export const LogoMark: React.FC<LogoMarkProps> = ({
  size = 32,
  inverse,
  lightFrame,
  className = '',
}) => {
  const theme = useThemeStore((s) => s.theme)
  // 优先级: explicit inverse > explicit lightFrame > 主题推断
  const useInverse = inverse ?? (lightFrame ? false : theme === 'dark')
  return (
    <img
      className={`logo-mark ${className}`.trim()}
      src={useInverse ? '/logo-mark-inverse.svg' : '/logo-mark.svg'}
      width={size}
      height={size}
      alt={brand.name}
      draggable={false}
    />
  )
}

/** 图形 + 名称的横排组合, 登录页与侧栏用 */
export const LogoLockup: React.FC<{ size?: number; subtitle?: string }> = ({
  size = 34,
  subtitle = brand.subtitle,
}) => (
  <div className="logo-lockup">
    <LogoMark size={size} />
    <div className="logo-lockup-text">
      <div className="logo-lockup-title">{brand.name}</div>
      {subtitle ? <div className="logo-lockup-sub">{subtitle}</div> : null}
    </div>
  </div>
)