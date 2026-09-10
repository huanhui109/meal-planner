#!/usr/bin/env node
/**
 * 从 shared/tokens.ts 生成两端的样式变量
 *
 *   node scripts/gen_tokens.mjs          写入生成物
 *   node scripts/gen_tokens.mjs --check  只校验是否与源一致 (CI 用)
 *
 * 生成物是"源"的下游, 不要手改: 改令牌请改 shared/tokens.ts。
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..')
const { tokens } = await import(resolve(repoRoot, 'shared/tokens.ts'))

const HEADER = '/* 自动生成, 请勿手改: 源文件是 shared/tokens.ts (node scripts/gen_tokens.mjs) */'

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

const flat = flatten(tokens)

const cssLines = [
  HEADER,
  ':root {',
  ...flat.map(([name, value]) => `  --${name}: ${value};`),
  '}',
  '',
]

const scssLines = [
  '// 自动生成, 请勿手改: 源文件是 shared/tokens.ts (node scripts/gen_tokens.mjs)',
  ...flat.map(([name, value]) => `$${name}: ${value};`),
  '',
  '// 小程序里同时暴露一份 CSS 变量, 运行时要覆盖时用 var(--x)',
  'page {',
  ...flat.map(([name, value]) => `  --${name}: ${value};`),
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
  console.log(`写入 ${relative} (${flat.length} 个令牌)`)
}

if (check && failed) process.exit(1)
