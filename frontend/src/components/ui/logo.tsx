/**
 * 品牌标识
 *
 * 图标本体是 assets/logo/logo-mark.svg (由 scripts/gen_logo.mjs 生成),
 * 这里只负责尺寸与无障碍属性, 不在代码里重画一遍几何, 避免 Logo 走样。
 *
 * 主题跟随 (V2.4 修正: 命名与映射对齐用户认知):
 *   - assets/logo/logo-mark.svg        —— 默认版, 深色容框 (深灰/冷色场景使用)
 *   - assets/logo/logo-mark-inverse.svg —— 反白版, 白色容框 (明亮/奶油场景使用)
 *   - 显式传 `inverse`   时强制白底容框, 优先级最高 (给硬性深色场景如启动封面/分享卡)
 *   - 显式传 `lightFrame` 强制深容框, 用于深色 UI 上的固定位置
 *
 * 自动推断: 明亮主题 = 白底容框 (亮色 UI 上的 logo 与奶油底融为一体, 只露出锅/蛋黄);
 *           深色主题 = 深色容框 (深色 UI 上的 logo 整体压暗, 保持品牌识别)。
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
  const theme = useThemeStore((s) => s.theme)
  // 优先级: explicit inverse > explicit lightFrame > 主题推断
  // 推断规则: 明亮主题 → 白底容框 (与奶油背景融为一体), 深色主题 → 深色容框
  const useInverse = inverse ?? (lightFrame ? false : theme === 'light')
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