/**
 * Ant Design 主题 - 把 antd 的默认观感对齐设计稿
 *
 * 交互组件 (Modal/Form/Input/Collapse/message) 的默认外观全部在这里换掉,
 * 页面里就不用逐个覆写样式了。设计令牌来自 shared/tokens.ts。
 */
import type { ThemeConfig } from 'antd'
import { tokens } from '@shared/tokens'

export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: tokens.color.ink,
    colorInfo: tokens.color.ink,
    colorSuccess: tokens.color.accent,
    colorWarning: tokens.color.warn,
    colorError: tokens.color.danger,
    colorText: tokens.color.ink,
    colorTextSecondary: tokens.color.ink2,
    colorTextTertiary: tokens.color.ink3,
    colorBgLayout: tokens.color.screen,
    colorBgContainer: tokens.color.card,
    colorBorder: tokens.color.line,
    colorBorderSecondary: tokens.color.line,
    colorFillSecondary: tokens.color.fill,
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
    Message: { contentBg: tokens.color.ink, colorText: tokens.color.onInk },
    Tag: { borderRadiusSM: 999 },
    Segmented: { borderRadius: 999 },
  },
}

export default antdTheme
