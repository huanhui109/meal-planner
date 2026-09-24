/**
 * Logo 组件 (小程序)
 *
 * 小程序没有 public 目录, Logo 是 scripts/gen_logo.mjs 生成的 base64 PNG 常量
 * (lib/logo.ts), 所以这里不能像 H5 那样直接 <img src="/logo-mark.svg">。
 *
 * 颜色映射与 H5 的 components/ui/logo.tsx 一致:
 *   cool (中性灰) → default (深容框)
 *   其余 (cream / dark) → inverse (白容框)
 */
import { Image } from '@tarojs/components'

import { brand } from '@shared/brand'
import { LOGO_MARK_DATA_URI, LOGO_MARK_DATA_URI_DARK } from '../lib/logo'
import { useTheme } from '../lib/theme'

export function LogoMark({ size = 32 }: { size?: number }) {
  const [, , applied] = useTheme()
  const src = applied !== 'cool' ? LOGO_MARK_DATA_URI_DARK : LOGO_MARK_DATA_URI
  return (
    <Image
      src={src}
      style={{ width: `${size}px`, height: `${size}px` }}
      mode="aspectFit"
      // 小程序的无障碍标签走 aria-label, 与 H5 的 alt 对应
      aria-label={brand.name}
    />
  )
}

export default LogoMark
