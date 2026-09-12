/**
 * 品牌标识 (V2.5: 三主题 + auto 跟随)
 *
 * 图标本体是 assets/logo/logo-mark.svg (由 scripts/gen_logo.mjs 生成),
 * 这里只负责尺寸与无障碍属性, 不在代码里重画一遍几何, 避免 Logo 走样。
 *
 * 主题跟随:
 *   - assets/logo/logo-mark.svg        —— 默认版, 深色容框 (冷色场景使用)
 *   - assets/logo/logo-mark-inverse.svg —— 反白版, 白色容框 (明亮/真·深色场景使用)
 *   - 显式传 `inverse`   时强制白底容框, 优先级最高 (给硬性深色场景如启动封面/分享卡)
 *   - 显式传 `lightFrame` 强制深容框, 用于深色 UI 上的固定位置
 *
 * 自动推断 (按 `applied` 字段, auto 模式下用解析后的实际主题):
 *   - cool  → 深色容框 (深色框压在冷灰底上, 品牌识别稳)
 *   - cream → 白底容框 (白框融入奶油底, 只露出锅/蛋黄/木柄)
 *   - dark  → 白底容框 (白框融入 #000, 只露出锅/蛋黄, 深色态下"反白"是 Apple HIG 惯例)
 */
import React from 'react'
import { brand } from '@shared/index'
import { useThemeStore } from '../../stores/useThemeStore'

interface LogoMarkProps {
  /** 显示边长 (px) */
  size?: number
  /** 强制使用白底容框版 (用于硬性深色背景, 如启动封面/分享卡) */
  inverse?: boolean
  /** 强制使用深色容框版 (用于深色 UI 上的固定位置) */
  lightFrame?: boolean
  className?: string
}

export const LogoMark: React.FC<LogoMarkProps> = ({
  size = 32,
  inverse,
  lightFrame,
  className = '',
}) => {
  // 用 applied (而非 theme) —— auto 模式下 applied 才是实际生效的 cool/dark
  const applied = useThemeStore((s) => s.applied)
  // 优先级: explicit inverse > explicit lightFrame > 主题推断
  const useInverse = inverse ?? (lightFrame ? false : applied !== 'cool')
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
