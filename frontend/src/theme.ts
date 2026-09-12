/**
 * Ant Design 主题 - 把 antd 的默认观感对齐设计稿
 *
 * 交互组件 (Modal/Form/Input/Collapse/message) 的默认外观全部在这里换掉,
 * 页面里就不用逐个覆写样式了。设计令牌来自 shared/tokens.ts。
 *
 * 主题跟随: antd 的 token 也需要随 UI 主题切换 (因为 antd 的 Modal/Input 不会读我们的
 * var(--color-*), 必须直接给它 token 值)。所以这里导出 `buildAntdTheme(theme)`,
 * 在 main.tsx 里通过 ThemeProviderWrapper 读 useThemeStore() 动态注入。
 */
import type { ThemeConfig } from 'antd'
import { tokens, palettes } from '@shared/tokens'

/** antd ThemeConfig 不吃 rgba 字符串以外的"颜色态"; 我们直接传语义色字符串 */
const buildAntdTheme = (theme: 'light' | 'dark'): ThemeConfig => {
  const p = palettes[theme]
  return {
    token: {
      colorPrimary: p.ink,
      colorInfo: p.ink,
      colorSuccess: p.accent,
      colorWarning: p.warn,
      colorError: p.danger,
      colorText: p.ink,
      colorTextSecondary: p.ink2,
      colorTextTertiary: p.ink3,
      colorBgLayout: p.screen,
      colorBgContainer: p.card,
      colorBorder: p.line,
      colorBorderSecondary: p.line,
      colorFillSecondary: p.fill,
      borderRadius: 16,
      borderRadiusLG: 22,
      borderRadiusSM: 12,
      controlHeight: 44,
      fontFamily: tokens.font.family,
      fontSize: 15,
    },
    components: {
      Button: {
        borderRadius: 999,
        borderRadiusLG: 999,
        borderRadiusSM: 999,
        primaryShadow: 'none',
        defaultShadow: 'none',
      },
      Modal: { borderRadiusLG: 28 },
      Message: { contentBg: p.ink, colorText: p.onInk },
      Tag: { borderRadiusSM: 999 },
      Segmented: { borderRadius: 999 },
    },
  }
}

// 旧版默认导出: 保持向后兼容 (调用方可能还在用 default import)
export const antdTheme: ThemeConfig = buildAntdTheme('light')

export { buildAntdTheme }

export default antdTheme