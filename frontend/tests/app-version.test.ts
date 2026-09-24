/**
 * R-16a: 埋点必须带真实 app_version
 *
 * 验收标准是"上报的 app_version 是真实版本号(非 unknown)", 而 event 表现有
 * 91 行这个字段 100% 是 unknown —— 忘了传或者传空, 后端会静默写成 unknown,
 * 没有任何告警。这里钉住两件事: 版本号非空且不是 unknown; 并且不许和
 * package.json 漂移(常量手写的代价就是这个)。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { APP_VERSION } from '../src/lib/app-version'

describe('app_version (R-16a)', () => {
  it('不是空值也不是 unknown', () => {
    expect(APP_VERSION).toBeTruthy()
    expect(APP_VERSION.toLowerCase()).not.toBe('unknown')
    expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+$/)
  })

  it('与 package.json 的 version 一致 —— 防止手改常量忘了同步', () => {
    const pkg = JSON.parse(
      readFileSync(fileURLToPath(new URL('../package.json', import.meta.url)), 'utf8'),
    ) as { version: string }
    expect(APP_VERSION).toBe(pkg.version)
  })
})
