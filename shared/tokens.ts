/**
 * 调色板: 冷色 / 明亮 / 真·深色 三套, 运行时切换 (V2.5)
 *
 * 命名收敛 (V2.4 → V2.5):
 *   旧 `dark` (冷灰底) → **`cool`** —— 中性灰底, 主按钮仍是品牌黑
 *   旧 `light` (奶油底) → **`cream`** —— 早餐店暖橙氛围
 *   新 `dark` (真·深色) —— 遵循 Apple HIG / HarmonyOS 暗色规范, 主背景 #000000
 *
 * 默认主题 (`:root` 块) = cool, 与 V2.0 逐字节相同, 老用户升级零感知。
 *
 * 三套色值要点:
 *   cool  (冷色):  bg #e9e9ee  card #ffffff  ink #1c1c1e
 *   cream (明亮):  bg #FBF9F4  card #FFFFFF  ink #2C2C2A  warn=#E0955A 暖橙
 *   dark  (深色):  bg #000000  card #1C1C1E  ink #FFFFFF  line rgba(84,84,88,0.65) 玻璃 #1C1C1E
 *
 * 黑色胶囊 (pill--ink / .next-step / .app-tab.is-active 等) 在 cool/cream 下用
 * var(--color-ink) 保持黑底; 在 dark 下用 var(--color-on-ink) 翻成白底黑字
 * (Apple 暗色下系统色按钮反色)。
 */
export const palettes = {
  cool: {
    bg: '#e9e9ee',
    screen: '#f7f7f9',
    card: '#ffffff',
    ink: '#1c1c1e',
    ink2: '#8e8e93',
    ink3: '#c7c7cc',
    line: '#efeff2',
    fill: '#f2f2f4',
    onInk: '#ffffff',
    accent: '#34c759',
    accentInk: '#1e7d3c',
    accentSoft: 'rgba(52, 199, 89, 0.12)',
    warn: '#ff9f0a',
    warnInk: '#c77800',
    warnSoft: 'rgba(255, 159, 10, 0.12)',
    danger: '#ff3b30',
    dangerSoft: 'rgba(255, 59, 48, 0.12)',
    glass: 'rgba(255, 255, 255, 0.82)',
  },
  cream: {
    bg: '#FBF9F4',
    screen: '#FFFFFF',
    card: '#FFFFFF',
    ink: '#2C2C2A',
    ink2: '#6B6B6B',
    ink3: 'rgba(0, 0, 0, 0.20)',
    line: 'rgba(0, 0, 0, 0.10)',
    fill: '#F2EDE4',
    onInk: '#FFFFFF',
    accent: '#34c759',
    accentInk: '#1e7d3c',
    accentSoft: 'rgba(52, 199, 89, 0.12)',
    warn: '#E0955A',
    warnInk: '#A8642F',
    warnSoft: 'rgba(224, 149, 90, 0.15)',
    danger: '#ff3b30',
    dangerSoft: 'rgba(255, 59, 48, 0.12)',
    glass: 'rgba(255, 254, 250, 0.82)',
  },
  dark: {
    // 真·深色 —— 遵循 Apple HIG Dark Mode + HarmonyOS 暗色规范
    // 主背景接近黑 (UIKit/HIG 用 #000000; Apple 设备上 OLED 真黑省电),
    // 卡片用 #1C1C1E 抬升 (Apple "secondarySystemBackground"),
    // 弹窗用 #2C2C2E ("tertiarySystemBackground"), 输入框 #3A3A3C ("quaternarySystemFill")
    bg: '#000000',
    screen: '#0A0A0C',
    card: '#1C1C1E',
    card2: '#2C2C2E',
    card3: '#3A3A3C',
    ink: '#FFFFFF',
    ink2: 'rgba(235, 235, 245, 0.60)',
    ink3: 'rgba(235, 235, 245, 0.30)',
    inkDisabled: 'rgba(235, 235, 245, 0.18)',
    line: 'rgba(84, 84, 88, 0.65)',
    fill: 'rgba(118, 118, 128, 0.24)',
    onInk: '#000000',
    accent: '#30D158',
    accentInk: '#30D158',
    accentSoft: 'rgba(48, 209, 88, 0.20)',
    warn: '#FF9F0A',
    warnInk: '#FFD60A',
    warnSoft: 'rgba(255, 159, 10, 0.20)',
    danger: '#FF453A',
    dangerSoft: 'rgba(255, 69, 58, 0.20)',
    glass: 'rgba(28, 28, 30, 0.72)',
  },
} as const

/** 用户可选的主题: 三种显式 + auto (跟随系统) */
export type PaletteName = 'cool' | 'cream' | 'dark'
export type ThemeName = PaletteName | 'auto'
export type Palette = (typeof palettes)[PaletteName]

/**
 * 解析 `auto` → 实际调色板名 (用于 H5 useThemeStore / 小程序 lib/theme)
 * 跟随 prefers-color-scheme: dark 时返回 'dark'，否则 'cool'
 */
export function resolveAutoTheme(): PaletteName {
  if (typeof window === 'undefined' || !window.matchMedia) return 'cool'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'cool'
}

/**
 * 设计令牌 - 全项目唯一真源
 *
 * H5 (frontend) 与小程序 (miniapp) 都从这里取值:
 *   node scripts/gen_tokens.mjs 会生成
 *     frontend/src/styles/tokens.css
 *       :root                              = cool 默认
 *       :root[data-theme="cream"] {}      = cream 覆盖
 *       :root[data-theme="dark"] {}       = dark 覆盖
 *     miniapp/src/styles/_tokens.scss
 *       $color-*  +  page{} (=cool) / page.theme-cream{} / page.theme-dark{}
 * CI 会跑 `--check`, 生成物与这里不一致就失败, 所以两端不会漂移。
 *
 * 取色依据设计稿: 中性灰承载 95% 的面积, 色彩只用来表语义
 * (绿 = 完成/充足, 橙 = 临期/超支), 主按钮用纯黑胶囊。
 */
export const tokens = {
  color: {
    // 默认块 = cool (与 palettes.cool 逐字段一致), 老用户升级零感知
    bg: '#e9e9ee',
    screen: '#f7f7f9',
    card: '#ffffff',
    ink: '#1c1c1e',
    ink2: '#8e8e93',
    ink3: '#c7c7cc',
    line: '#efeff2',
    fill: '#f2f2f4',
    onInk: '#ffffff',
    accent: '#34c759',
    accentInk: '#1e7d3c',
    accentSoft: 'rgba(52, 199, 89, 0.12)',
    warn: '#ff9f0a',
    warnInk: '#c77800',
    warnSoft: 'rgba(255, 159, 10, 0.12)',
    danger: '#ff3b30',
    dangerSoft: 'rgba(255, 59, 48, 0.12)',
    glass: 'rgba(255, 255, 255, 0.82)',
  },
  radius: {
    xl: '28px',
    lg: '22px',
    md: '16px',
    sm: '12px',
    pill: '999px',
  },
  font: {
    family:
      '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
    title: '29px',
    heading: '19px',
    body: '15px',
    label: '13px',
    caption: '12px',
    micro: '11px',
    number: '26px',
    tracking: '-0.01em',
    trackingTight: '-0.03em',
  },
  shadow: {
    // 卡片阴影: cool/cream 用常规黑色阴影; dark 模式通过 CSS 媒体查询覆盖为描边
    card: '0 1px 2px rgba(0, 0, 0, 0.025), 0 10px 30px -18px rgba(0, 0, 0, 0.12)',
    float: '0 12px 32px -12px rgba(0, 0, 0, 0.18)',
    lift: '0 18px 40px -18px rgba(0, 0, 0, 0.45)',
  },
  motion: {
    ease: 'cubic-bezier(0.22, 0.9, 0.3, 1)',
    press: '0.965',
    fast: '0.14s',
    base: '0.24s',
  },
  layout: {
    pageMax: '1120px',
    tabbarHeight: '74px',
    tapTarget: '44px',
  },
  /**
   * 品牌色 (只服务于 Logo, 不参与语义配色)
   *
   * 取自品牌故事「平底锅颠荷包蛋」: 白底容框, 深色锅身, 木色锅柄,
   * 蛋黄与动势线是画面上仅有的暖色。渐变压成中间色, 保持扁平。
   */
  brand: {
    /** 容框 (默认: 白底, 浅色场景) */
    frame: '#ffffff',
    frameLine: '#ededed',
    /** 容框 (深色底专用版) */
    frameDark: '#1c1c1e',
    /** 锅身 / 锅沿 / 锅内 */
    pan: '#3b4048',
    panRim: '#6b7280',
    panInner: '#2b2f35',
    /** 深色底上的浅色锅 */
    panLight: '#e8e8ea',
    panLightRim: '#f4f4f6',
    panLightInner: '#c9c9ce',
    /** 锅柄木色 */
    wood: '#c9824a',
    /** 蛋黄 / 高光 */
    yolk: '#f6a623',
    yolkLight: '#ffc861',
    /** 颠动的两道弧线 */
    motion: '#f2b872',
    /** 蛋白 / 蛋白描边 */
    egg: '#ffffff',
    eggLine: '#dadada',
  },
} as const

export type Tokens = typeof tokens

/** 数字统一用等宽数字字形, 金额/热量/进度对齐后更"亲近" */
export const numericFont = {
  fontVariantNumeric: 'tabular-nums',
  fontFeatureSettings: '"tnum"',
} as const

export default tokens
