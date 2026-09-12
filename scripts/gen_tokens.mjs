#!/usr/bin/env node
/**
 * 从 shared/tokens.ts 生成两端的样式变量
 *
 *   node scripts/gen_tokens.mjs          写入生成物
 *   node scripts/gen_tokens.mjs --check  只校验是否与源一致 (CI 用)
 *
 * 生成物是"源"的下游, 不要手改: 改令牌请改 shared/tokens.ts。
 *
 * 双调色板输出结构:
 *   H5   - :root { --color-*: <dark> }                          默认暗色, 与旧版逐字节相同
 *         :root[data-theme="light"] { --color-*: <light> }      亮色覆盖
 *   小程序 - 与 H5 同结构, 只是挂在 page{} / page.theme-light{}
 *
 * 设计依据:
 *   * 现有页面样式几乎全是 var(--color-*); 只需要一份 :root 默认值 + 一份 light 覆盖
 *     就能在两套主题间切换, 老用户升级零感知。
 *   * 黑色胶囊 (pill--ink / .next-step / .app-tab.is-active 等) 在两套下都用
 *     var(--color-ink); 亮色下 ink = #2C2C2A (几乎与 #1c1c1e 不可辨), 胶囊跨主题仍是黑的,
 *     保留品牌识别。
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
// 默认 :root{} 块 (暗色) + :root[data-theme="light"]{} 覆盖块
// ---------------------------------------------------------------------------

/** 暗色块的色值条目 (= tokens.color, 带 'color' 前缀) */
const colorEntries = flatten(tokens.color, ['color'])

/** 亮色块色值条目 (= palettes.light), 顺序与暗色一一对应 */
const lightColorEntries = flatten(palettes.light, ['color'])

const cssLines = [
  HEADER_CSS,
  ':root {',
  ...colorEntries.map(([name, value]) => `  --${name}: ${value};`),
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
// SCSS: 全部 token (含 $color-*) + page{} / page.theme-light{} 的 CSS 变量
// ---------------------------------------------------------------------------

const flatAll = flatten(tokens)

const scssLines = [
  HEADER_SCSS,
  ...flatAll.map(([name, value]) => `$${name}: ${value};`),
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
  console.log(`写入 ${relative} (${colorEntries.length} 个颜色令牌 × 2 调色板)`)
}

if (check && failed) process.exit(1)