#!/usr/bin/env node
/**
 * 从 shared/tokens.ts 生成两端的样式变量
 *
 *   node scripts/gen_tokens.mjs          写入生成物
 *   node scripts/gen_tokens.mjs --check  只校验是否与源一致 (CI 用)
 *
 * 输出结构 (V2.5 三调色板 + 保留 V2.0 的全令牌):
 *   - :root { --color-*: cool 默认;  --radius/font/shadow/motion/layout/brand: 静态令牌 }
 *   - :root[data-theme="cream"] { --color-*: cream 覆盖 }
 *   - :root[data-theme="dark"]  { --color-*: dark 覆盖 (含 card-2/card-3/ink-disabled 扩展) }
 *
 * 命名约定 (V2.5 命名收敛):
 *   - 旧 `dark`  → **`cool`** (冷灰, 旧 V2.0 默认)
 *   - 旧 `light` → **`cream`** (奶油, 旧明亮主题)
 *   - 新 `dark`  → 真·深色, 遵循 Apple HIG / HarmonyOS 暗色规范
 *
 * 设计依据:
 *   * 现有页面样式 95% 都是 var(--color-*) + var(--radius-*) + var(--font-*);
 *     把它们都进 :root, 切换主题时只需要重新覆盖颜色一组变量即可,
 *     老用户升级零感知 (默认主题的 :root 与 V2.0 逐字节相同)。
 *   * 静态令牌 (圆角/字号/阴影/动效/布局/品牌色) 在三套主题下保持不变,
 *     不暴露 `[data-theme="..."]` 覆盖块, 减少重复。
 *   * `data-theme="auto"` 由 useThemeStore 在运行时根据 prefers-color-scheme
 *     解析为 cool 或 dark, 不需要 CSS 端 `@media` (避免与显式选择冲突)。
 *   * 黑色胶囊 (pill--ink / .next-step / .app-tab.is-active) 在 cool/cream 下用
 *     var(--color-ink) 保持黑底; 在 dark 下用 var(--color-on-ink) 翻成白底黑字
 *     (Apple 暗色下系统色按钮反色)。
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..')
const { tokens, palettes } = await import(resolve(repoRoot, 'shared/tokens.ts'))

const HEADER_CSS = '/* 自动生成, 请勿手改: 源文件是 shared/tokens.ts (node scripts/gen_tokens.mjs) */'
const HEADER_SCSS = '// 自动生成, 请勿手改: 源文件是 shared/tokens.ts (node scripts/gen_tokens.mjs)'

/** camelCase 键名转 kebab-case: pageMax -> page-max, ink2 -> ink2 */
function kebab(key) {
  return String(key)
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .toLowerCase()
}

/**
 * 把嵌套令牌拉平成 --a-b 形式的变量名
 *
 * 多词键名一律转成 kebab-case, 保证生成的变量名和手写 CSS 里的
 * var(--color-accent-ink) / var(--layout-page-max) 对得上。
 */
function flatten(node, prefix = []) {
  const out = []
  for (const [key, value] of Object.entries(node)) {
    const path = [...prefix, kebab(key)]
    if (value && typeof value === 'object') {
      out.push(...flatten(value, path))
    } else {
      out.push([path.join('-'), String(value)])
    }
  }
  return out
}

// ---------------------------------------------------------------------------
// 颜色: --color-* (三调色板: :root 默认 cool + cream / dark 覆盖)
// ---------------------------------------------------------------------------

const colorEntries = flatten(tokens.color, ['color'])
const creamColorEntries = flatten(palettes.cream, ['color'])
const darkColorEntries = flatten(palettes.dark, ['color'])

// dark 调色板比 cool/cream 多三个字段 (card-2 / card-3 / ink-disabled),
// 它们是深色模式专属的"二级/三级 surface"和"禁用态"; 在 :root 默认块里
// 也要给出回退值, 否则 cool/cream 主题下 var(--color-card-2) 会失效
const darkOnlyColorNames = darkColorEntries
  .map(([name]) => name)
  .filter((name) => !colorEntries.some(([n]) => n === name))

// ---------------------------------------------------------------------------
// 静态令牌: radius / font / shadow / motion / layout / brand (只一份, 不分主题)
// ---------------------------------------------------------------------------

const staticEntries = [
  ...flatten(tokens.radius, ['radius']),
  ...flatten(tokens.font, ['font']),
  ...flatten(tokens.shadow, ['shadow']),
  ...flatten(tokens.motion, ['motion']),
  ...flatten(tokens.layout, ['layout']),
  ...flatten(tokens.brand, ['brand']),
]

// :root 默认块: 全部颜色 (cool) + dark 专属颜色的 cool 回退 + 全部静态令牌
const rootEntries = [
  ...colorEntries,
  // dark 专属字段在 :root 用 cool 调色板里的"相邻字段"做回退, 避免 var(--color-card-2) 在浅色下失效
  ...darkOnlyColorNames.map((name) => {
    // card-2 / card-3 → card; ink-disabled → ink3
    const fallbackKey = name === 'color-card-2' || name === 'color-card-3'
      ? 'color-card'
      : name === 'color-ink-disabled'
        ? 'color-ink3'
        : null
    const fallback = fallbackKey ? colorEntries.find(([n]) => n === fallbackKey) : null
    return [name, fallback ? fallback[1] : 'transparent']
  }),
  ...staticEntries,
]

// ---------------------------------------------------------------------------
// CSS: :root { 全部 } + :root[data-theme=cream] { --color-* } + :root[data-theme=dark] { --color-* }
// ---------------------------------------------------------------------------

function buildOverrideBlock(selector, paletteEntries) {
  // paletteEntries 与 colorEntries 顺序一一对应 (flatten 顺序与 Object.entries 一致)
  // 但 dark 可能多出字段, 用名字匹配而不是 index 匹配更稳
  return [
    selector + ' {',
    ...colorEntries.map(([name]) => {
      const found = paletteEntries.find(([n]) => n === name)
      return `  --${name}: ${found ? found[1] : 'inherit'};`
    }),
    // dark 多出的字段也写进 dark 覆盖块; cream 覆盖块不带这些
    ...paletteEntries
      .filter(([name]) => !colorEntries.some(([n]) => n === name))
      .map(([name, value]) => `  --${name}: ${value};`),
    '}',
    '',
  ]
}

const cssLines = [
  HEADER_CSS,
  ':root {',
  ...rootEntries.map(([name, value]) => `  --${name}: ${value};`),
  '}',
  '',
  ...buildOverrideBlock(':root[data-theme="cream"]', creamColorEntries),
  ...buildOverrideBlock(':root[data-theme="dark"]', darkColorEntries),
]

// ---------------------------------------------------------------------------
// SCSS: 全部 token (含 $color-*) + page{} (cool) + page.theme-cream{} + page.theme-dark{}
// ---------------------------------------------------------------------------

function buildScssOverrideBlock(selector, paletteEntries) {
  return [
    selector + ' {',
    ...colorEntries.map(([name]) => {
      const found = paletteEntries.find(([n]) => n === name)
      return `  --${name}: ${found ? found[1] : 'inherit'};`
    }),
    ...paletteEntries
      .filter(([name]) => !colorEntries.some(([n]) => n === name))
      .map(([name, value]) => `  --${name}: ${value};`),
    '}',
    '',
  ]
}

const scssLines = [
  HEADER_SCSS,
  ...rootEntries.map(([name, value]) => `$${name}: ${value};`),
  '',
  '// 小程序里同时暴露一份 CSS 变量, 运行时要覆盖时用 var(--x)',
  'page {',
  ...colorEntries.map(([name, value]) => `  --${name}: ${value};`),
  '}',
  '',
  ...buildScssOverrideBlock('page.theme-cream', creamColorEntries),
  ...buildScssOverrideBlock('page.theme-dark', darkColorEntries),
]

const targets = [
  ['frontend/src/styles/tokens.css', cssLines.join('\n')],
  ['miniapp/src/styles/_tokens.scss', scssLines.join('\n')],
]

const check = process.argv.includes('--check')
let failed = false

for (const [relative, content] of targets) {
  const absolute = resolve(repoRoot, relative)
  const current = existsSync(absolute) ? readFileSync(absolute, 'utf8') : null
  if (check) {
    if (current !== content) {
      failed = true
      console.error(`✗ ${relative} 与 shared/tokens.ts 不一致, 请运行: node scripts/gen_tokens.mjs`)
    } else {
      console.log(`✓ ${relative}`)
    }
    continue
  }
  mkdirSync(dirname(absolute), { recursive: true })
  writeFileSync(absolute, content, 'utf8')
  console.log(`写入 ${relative} (${rootEntries.length} 个令牌, ${colorEntries.length} 个颜色 × 3 调色板)`)
}

if (check && failed) process.exit(1)
