/**
 * Ant Design 主题 - 把 antd 的默认观感对齐设计稿
 *
 * 交互组件 (Modal/Form/Input/Collapse/message) 的默认外观全部在这里换掉,
 * 页面里就不用逐个覆写样式了。设计令牌来自 shared/tokens.ts。
 *
 * 主题跟随: antd 的 token 也需要随 UI 主题切换 (因为 antd 的 Modal/Input 不会读我们的
 * var(--color-*), 必须直接给它 token 值)。所以这里导出 `buildAntdTheme(applied)`,
 * 在 main.tsx 里通过 ThemedProviders 读 useThemeStore().applied 动态注入。
 *
 * V2.5: 用 `applied` 字段 (而非 theme) —— auto 模式下 applied 才是实际生效主题,
 * 否则 antd 看到 'auto' 会用默认色, 跟 html[data-theme] 不一致。
 */
import type { ThemeConfig } from 'antd'
import { theme as antdThemeAlg } from 'antd'
import { tokens, palettes, type PaletteName } from '@shared/index'

const buildAntdTheme = (applied: PaletteName): ThemeConfig => {
  const p = palettes[applied]
  return {
    // 真·深色下用 antd 5 自带的 dark algorithm (它会处理 Switch/DatePicker 等
    // 内部子组件的暗色调; 我们自己的 token 仍由 palettes.dark 提供)
    algorithm: applied === 'dark' ? antdThemeAlg.darkAlgorithm : antdThemeAlg.defaultAlgorithm,
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
      colorBgElevated: applied === 'dark' ? palettes.dark.card2 : p.card,
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
export const antdTheme: ThemeConfig = buildAntdTheme('cool')

export { buildAntdTheme }

export default antdTheme
