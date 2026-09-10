/**
 * 品牌标识
 *
 * 图标本体是 assets/logo/logo-mark.svg (由 scripts/gen_logo.mjs 生成),
 * 这里只负责尺寸与无障碍属性, 不在代码里重画一遍几何, 避免 Logo 走样。
 */
import React from 'react'
import { brand } from '@shared/index'

interface LogoMarkProps {
  /** 显示边长 (px) */
  size?: number
  /** 深色背景上换成白底反白版 */
  inverse?: boolean
  className?: string
}

export const LogoMark: React.FC<LogoMarkProps> = ({ size = 32, inverse, className = '' }) => (
  <img
    className={`logo-mark ${className}`.trim()}
    src={inverse ? '/logo-mark-inverse.svg' : '/logo-mark.svg'}
    width={size}
    height={size}
    alt={brand.name}
    draggable={false}
  />
)

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
