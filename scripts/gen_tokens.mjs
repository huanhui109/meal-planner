#!/usr/bin/env node
/**
 * 从 shared/tokens.ts 生成两端的样式变量
 *
 *   node scripts/gen_tokens.mjs          写入生成物
 *   node scripts/gen_tokens.mjs --check  只校验是否与源一致 (CI 用)
 *
 * 输出结构 (V2.4 合并 V2.3 的双调色板 + 保留 V2.0 的全令牌):
 *   - :root { --color-*: dark 默认色;  --radius/font/shadow/motion/layout/brand: 静态令牌 }
 *   - :root[data-theme="light"] { --color-*: 亮色色 }
 *
 * 设计依据:
 *   * 现有页面样式 95% 都是 var(--color-*) + var(--radius-*) + var(--font-*);
 *     把它们都进 :root, 切换主题时只需要重新覆盖颜色一组变量即可,
 *     老用户升级零感知 (默认主题的 :root 与旧版逐字节相同)。
 *   * 静态令牌 (圆角/字号/阴影/动效/布局/品牌色) 在两套主题下保持不变,
 *     不暴露 `[data-theme="light"]` 覆盖块, 减少重复。
 *   * 黑色胶囊 (pill--ink / .next-step / .app-tab.is-active) 在两套下都用
 *     var(--color-ink); 亮色下 ink = #2C2C2A (几乎与 #1c1c1e 不可辨),
 *     黑色胶囊的"品牌识别"自然跨主题稳住。
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
// 颜色: --color-* (双调色板: :root 默认暗 + :root[data-theme=light] 亮)
// ---------------------------------------------------------------------------

const colorEntries = flatten(tokens.color, ['color'])
const lightColorEntries = flatten(palettes.light, ['color'])

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

const rootEntries = [...colorEntries, ...staticEntries]

// ---------------------------------------------------------------------------
// CSS: :root { 全部 } + :root[data-theme=light] { --color-* }
// ---------------------------------------------------------------------------

const cssLines = [
  HEADER_CSS,
  ':root {',
  ...rootEntries.map(([name, value]) => `  --${name}: ${value};`),
  '}',
  '',
  ':root[data-theme="light"] {',
  ...colorEntries.map(([name], index) => {
    const [, lightValue] = lightColorEntries[index]
    return `  --${name}: ${lightValue};`
  }),
  '}',
  '',
]

// ---------------------------------------------------------------------------
// SCSS: 全部 token (含 $color-*) + page{} (暗) + page.theme-light{} (亮)
// ---------------------------------------------------------------------------

const scssLines = [
  HEADER_SCSS,
  ...rootEntries.map(([name, value]) => `$${name}: ${value};`),
  '',
  '// 小程序里同时暴露一份 CSS 变量, 运行时要覆盖时用 var(--x)',
  'page {',
  ...colorEntries.map(([name, value]) => `  --${name}: ${value};`),
  '}',
  '',
  'page.theme-light {',
  ...colorEntries.map(([name], index) => {
    const [, lightValue] = lightColorEntries[index]
    return `  --${name}: ${lightValue};`
  }),
  '}',
  '',
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
  console.log(`写入 ${relative} (${rootEntries.length} 个令牌, ${colorEntries.length} 个颜色 × 2 调色板)`)
}

if (check && failed) process.exit(1)