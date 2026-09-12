/**
 * 调色板: 暗色 / 明亮 两套, 运行时切换
 *
 * 暗色与上方 `color.*` 逐字段一致 —— 现有 `:root { --color-* }` 默认块就等于"暗色",
 * `data-theme="light"` 时再用 `--palette-light-*` 覆盖, 老用户升级零感知。
 *
 * 明亮色取自 `pan-egg/preview.html` 的奶油暖色系:
 *   bg #FBF9F4  ink #2C2C2A  sub #6B6B6B  line rgba(0,0,0,.10)  fill #F2EDE4
 *   warn 改用品牌暖橙 #E0955A (preview 里 .brand-head .tag 的色), 增强"早餐店"氛围;
 *   accent(绿)/danger(红) 保留原语义色, 不强行换。
 *
 * 主按钮 (pill--ink / .next-step / .app-tab.is-active / .chip-option--on) 在两套下都
 * 是深色 —— 因为 `var(--color-ink)` 既是主文字也是黑胶囊底, 亮色下 ink = #2C2C2A
 * (与 #1c1c1e 几乎不可辨), 黑色胶囊的"品牌识别"自然跨主题稳住。
 */
export const palettes = {
  dark: {
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
  light: {
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
} as const

export type PaletteName = keyof typeof palettes
export type Palette = (typeof palettes)[PaletteName]

/**
 * 设计令牌 - 全项目唯一真源
 *
 * H5 (frontend) 与小程序 (miniapp) 都从这里取值:
 *   node scripts/gen_tokens.mjs 会生成
 *     frontend/src/styles/tokens.css   (:root + :root[data-theme="light"] 上的 CSS 变量)
 *     miniapp/src/styles/_tokens.scss  (SCSS 变量 + page{}/page.theme-light{} 的 CSS 变量)
 * CI 会跑 `--check`, 生成物与这里不一致就失败, 所以两端不会漂移。
 *
 * 取色依据设计稿: 中性灰承载 95% 的面积, 色彩只用来表语义
 * (绿 = 完成/充足, 橙 = 临期/超支), 主按钮用纯黑胶囊。
 */
export const tokens = {
  color: {
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
