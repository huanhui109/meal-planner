#!/usr/bin/env node
/**
 * 生成「每周鲜」品牌资源
 *
 *   node scripts/gen_logo.mjs          写入 SVG 与 PNG
 *   node scripts/gen_logo.mjs --check  只校验产物是否与脚本一致 (CI 用)
 *
 * 两个刻意的设计决定:
 *   1. 图形只有一份几何定义 (下面的 SHAPES / markLayers), SVG 与 PNG 都从它渲染,
 *      所以矢量和位图不可能画歪。
 *   2. 光栅化不引任何依赖: 用扫描线覆盖度 + 4 倍子采样做抗锯齿, 再用内置 zlib
 *      手写 PNG。这样 CI 里不需要 sharp / canvas / rsvg 之类的原生依赖。
 *
 * 配色全部读 shared/tokens.ts, Logo 不会和设计系统漂移。
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { deflateSync } from 'node:zlib'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..')
const { tokens } = await import(resolve(repoRoot, 'shared/tokens.ts'))
const C = tokens.color

// ---------------------------------------------------------------------------
// 几何: 全部在 96x96 的网格里描述, 是 SVG 与 PNG 共同的唯一真源
// ---------------------------------------------------------------------------

const GRID = 96
const BASE_RADIUS = 28
const BOWL_CENTER = [48, 47]
const BOWL_RADIUS = 21
/** 7 个点 = 一周 7 天, 摊在碗里; 最后一个点用绿色表示"今天" */
const DOT_Y = 54
const DOT_RADIUS = 2.4
const DOT_COUNT = 7
const DOT_X0 = 33
const DOT_STEP = 5

function roundRectPoints(x, y, w, h, r, seg = 8) {
  const corners = [
    [x + w - r, y + r, -Math.PI / 2, 0],
    [x + w - r, y + h - r, 0, Math.PI / 2],
    [x + r, y + h - r, Math.PI / 2, Math.PI],
    [x + r, y + r, Math.PI, Math.PI * 1.5],
  ]
  const points = []
  for (const [cx, cy, from, to] of corners) {
    for (let i = 0; i <= seg; i += 1) {
      const angle = from + ((to - from) * i) / seg
      points.push([cx + r * Math.cos(angle), cy + r * Math.sin(angle)])
    }
  }
  return points
}

function circlePoints(cx, cy, r, seg = 72) {
  const points = []
  for (let i = 0; i < seg; i += 1) {
    const angle = (Math.PI * 2 * i) / seg
    points.push([cx + r * Math.cos(angle), cy + r * Math.sin(angle)])
  }
  return points
}

/** 碗 = 下半圆 (inner > 0 时变成一道等宽描边环, 单色版用) */
function bowlPoints(r, inner = 0, seg = 64) {
  const [cx, cy] = BOWL_CENTER
  const points = []
  for (let i = 0; i <= seg; i += 1) {
    const angle = (Math.PI * i) / seg
    points.push([cx + r * Math.cos(angle), cy + r * Math.sin(angle)])
  }
  if (inner > 0) {
    for (let i = seg; i >= 0; i -= 1) {
      const angle = (Math.PI * i) / seg
      points.push([cx + inner * Math.cos(angle), cy + inner * Math.sin(angle)])
    }
  }
  return points
}

function cubicPoints(p0, p1, p2, p3, seg = 32) {
  const points = []
  for (let i = 0; i <= seg; i += 1) {
    const t = i / seg
    const k = 1 - t
    const x =
      k * k * k * p0[0] + 3 * k * k * t * p1[0] + 3 * k * t * t * p2[0] + t * t * t * p3[0]
    const y =
      k * k * k * p0[1] + 3 * k * k * t * p1[1] + 3 * k * t * t * p2[1] + t * t * t * p3[1]
    points.push([x, y])
  }
  return points
}

/** 叶子: 两片旋转椭圆构成的豆芽形, 小尺寸下也能认出是"嫩叶" */
function ellipsePoints(cx, cy, rx, ry, rotationDeg, seg = 56) {
  const rotation = (rotationDeg * Math.PI) / 180
  const cos = Math.cos(rotation)
  const sin = Math.sin(rotation)
  const points = []
  for (let i = 0; i < seg; i += 1) {
    const angle = (Math.PI * 2 * i) / seg
    const x = rx * Math.cos(angle)
    const y = ry * Math.sin(angle)
    points.push([cx + x * cos - y * sin, cy + x * sin + y * cos])
  }
  return points
}

/** 图标的分层定义: 顺序即绘制顺序 (先底后上) */
function markLayers(theme) {
  const layers = []
  if (theme.base) {
    layers.push({ fill: theme.base, points: roundRectPoints(0, 0, GRID, GRID, BASE_RADIUS) })
  }
  layers.push({ fill: theme.leaf, points: ellipsePoints(41.5, 37.5, 9, 4.8, 48) })
  layers.push({ fill: theme.leaf, points: ellipsePoints(54.5, 37.5, 9, 4.8, -48) })
  if (theme.bowlRing) {
    layers.push({ fill: theme.bowl, points: bowlPoints(BOWL_RADIUS, BOWL_RADIUS - 3) })
  } else {
    layers.push({ fill: theme.bowl, points: bowlPoints(BOWL_RADIUS) })
  }
  for (let i = 0; i < DOT_COUNT; i += 1) {
    const isToday = i === DOT_COUNT - 1
    layers.push({
      fill: isToday ? theme.today : theme.dot,
      points: circlePoints(DOT_X0 + i * DOT_STEP, DOT_Y, DOT_RADIUS),
    })
  }
  return layers
}

const THEMES = {
  /** 默认: 深色圆角方底, 浅色背景上使用 (favicon / 头像 / 应用图标) */
  default: { base: C.ink, bowl: C.card, leaf: C.accent, dot: C.ink3, today: C.accent },
  /** 反白: 白色圆角方底, 深色背景上使用 */
  inverse: { base: C.card, bowl: C.ink, leaf: C.accentInk, dot: C.ink3, today: C.accentInk },
  /** 单色: 无底, 全部一个颜色, 给飞书卡片 / 深色底 / 单色印刷用 */
  mono: { base: null, bowl: '#ffffff', bowlRing: true, leaf: '#ffffff', dot: '#ffffff', today: '#ffffff' },
}

// ---------------------------------------------------------------------------
// SVG 输出
// ---------------------------------------------------------------------------

const fmt = (value) => {
  const rounded = Math.round(value * 100) / 100
  return String(rounded)
}

function polygonTag(layer) {
  const points = layer.points.map(([x, y]) => `${fmt(x)},${fmt(y)}`).join(' ')
  return `  <polygon points="${points}" fill="${layer.fill}" />`
}

function markSvg(themeName) {
  const layers = markLayers(THEMES[themeName])
  return [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96" role="img" aria-label="每周鲜">',
    '  <title>每周鲜</title>',
    ...layers.map(polygonTag),
    '</svg>',
    '',
  ].join('\n')
}

function fullLogoSvg() {
  const layers = markLayers(THEMES.default)
  const d = tokens.font.family.replace(/"/g, "'")
  return [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 120" width="300" height="120" role="img" aria-label="每周鲜 · AI 营养菜谱">',
    '  <title>每周鲜 · AI 营养菜谱</title>',
    '  <g transform="translate(12 12)">',
    ...layers.map((layer) => `    ${polygonTag(layer).trim()}`),
    '  </g>',
    `  <text x="128" y="60" font-family="${d}" font-size="38" font-weight="700" letter-spacing="-1.2" fill="${C.ink}">每周鲜</text>`,
    `  <text x="130" y="86" font-family="${d}" font-size="15" letter-spacing="3" fill="${C.ink2}">AI 营养菜谱</text>`,
    '</svg>',
    '',
  ].join('\n')
}

// ---------------------------------------------------------------------------
// PNG 光栅化: 扫描线覆盖度 + 4 倍子采样, 无外部依赖
// ---------------------------------------------------------------------------

const hexToRgb = (hex) => {
  const value = hex.replace('#', '')
  const full =
    value.length === 3
      ? value
          .split('')
          .map((ch) => ch + ch)
          .join('')
      : value
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ]
}

const SUB_ROWS = 4

function addSpan(buffer, width, row, from, to, weight) {
  let xa = Math.max(0, from)
  let xb = Math.min(width, to)
  if (xb <= xa) return
  const base = row * width
  const first = Math.floor(xa)
  const last = Math.floor(xb - 1e-9)
  if (first === last) {
    buffer[base + first] += weight * (xb - xa)
    return
  }
  buffer[base + first] += weight * (first + 1 - xa)
  for (let x = first + 1; x < last; x += 1) buffer[base + x] += weight
  buffer[base + last] += weight * (xb - last)
}

/** 返回每个像素被多边形覆盖的比例 (0-1) */
function coverage(points, width, height) {
  const buffer = new Float32Array(width * height)
  const count = points.length
  let minY = Infinity
  let maxY = -Infinity
  for (const [, y] of points) {
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }
  const rowFrom = Math.max(0, Math.floor(minY))
  const rowTo = Math.min(height - 1, Math.ceil(maxY))
  const crossings = []
  for (let row = rowFrom; row <= rowTo; row += 1) {
    for (let sub = 0; sub < SUB_ROWS; sub += 1) {
      const scanY = row + (sub + 0.5) / SUB_ROWS
      crossings.length = 0
      for (let i = 0; i < count; i += 1) {
        const [ax, ay] = points[i]
        const [bx, by] = points[(i + 1) % count]
        if (ay > scanY !== by > scanY) {
          crossings.push(ax + ((scanY - ay) / (by - ay)) * (bx - ax))
        }
      }
      crossings.sort((a, b) => a - b)
      for (let i = 0; i + 1 < crossings.length; i += 2) {
        addSpan(buffer, width, row, crossings[i], crossings[i + 1], 1 / SUB_ROWS)
      }
    }
  }
  return buffer
}

function paint(canvas, width, height, points, hex, alpha = 1) {
  const [r, g, b] = hexToRgb(hex)
  const cov = coverage(points, width, height)
  for (let i = 0; i < width * height; i += 1) {
    const a = Math.min(1, cov[i]) * alpha
    if (a <= 0) continue
    const offset = i * 4
    const da = canvas[offset + 3] / 255
    const oa = a + da * (1 - a)
    if (oa <= 0) continue
    canvas[offset] = (r * a + canvas[offset] * da * (1 - a)) / oa
    canvas[offset + 1] = (g * a + canvas[offset + 1] * da * (1 - a)) / oa
    canvas[offset + 2] = (b * a + canvas[offset + 2] * da * (1 - a)) / oa
    canvas[offset + 3] = Math.round(oa * 255)
  }
}

const CRC_TABLE = (() => {
  const table = new Int32Array(256)
  for (let n = 0; n < 256; n += 1) {
    let c = n
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c
  }
  return table
})()

function crc32(buffer) {
  let c = -1
  for (let i = 0; i < buffer.length; i += 1) c = CRC_TABLE[(c ^ buffer[i]) & 0xff] ^ (c >>> 8)
  return (c ^ -1) >>> 0
}

function pngChunk(type, data) {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length, 0)
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body), 0)
  return Buffer.concat([length, body, crc])
}

function encodePng(width, height, canvas) {
  const stride = width * 4
  const raw = Buffer.alloc((stride + 1) * height)
  for (let y = 0; y < height; y += 1) {
    raw[y * (stride + 1)] = 0
    Buffer.from(canvas.buffer, y * stride, stride).copy(raw, y * (stride + 1) + 1)
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8
  ihdr[9] = 6
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', deflateSync(raw, { level: 9 })),
    pngChunk('IEND', Buffer.alloc(0)),
  ])
}

/** 把 96 网格里的图层渲染成 size x size 的 PNG */
function renderMark(size, themeName) {
  const canvas = new Uint8Array(size * size * 4)
  const scale = size / GRID
  for (const layer of markLayers(THEMES[themeName])) {
    paint(
      canvas,
      size,
      size,
      layer.points.map(([x, y]) => [x * scale, y * scale]),
      layer.fill,
    )
  }
  return encodePng(size, size, canvas)
}

/** 5:4 分享卡: 浅底 + 居中图标 */
function renderShareCard(width = 500, height = 400) {
  const canvas = new Uint8Array(width * height * 4)
  paint(canvas, width, height, roundRectPoints(0, 0, width, height, 0), C.screen)
  const markSize = 240
  const scale = markSize / GRID
  const offsetX = (width - markSize) / 2
  const offsetY = (height - markSize) / 2 - 12
  for (const layer of markLayers(THEMES.default)) {
    paint(
      canvas,
      width,
      height,
      layer.points.map(([x, y]) => [x * scale + offsetX, y * scale + offsetY]),
      layer.fill,
    )
  }
  return encodePng(width, height, canvas)
}

// ---------------------------------------------------------------------------
// 产物
// ---------------------------------------------------------------------------

const markDefault = markSvg('default')
const targets = [
  ['assets/logo/logo-mark.svg', markDefault],
  ['assets/logo/logo-mark-inverse.svg', markSvg('inverse')],
  ['assets/logo/logo-mono.svg', markSvg('mono')],
  ['assets/logo/logo-full.svg', fullLogoSvg()],
  ['frontend/public/logo-mark.svg', markDefault],
  ['frontend/public/logo-mark-inverse.svg', markSvg('inverse')],
  ['frontend/public/favicon.svg', markDefault],
  ['frontend/public/favicon.png', renderMark(64, 'default')],
  ['frontend/public/logo-mark@2x.png', renderMark(192, 'default')],
  ['assets/logo/logo-mark@3x.png', renderMark(288, 'default')],
  ['miniapp/src/assets/logo-mark.png', renderMark(192, 'default')],
  ['miniapp/src/assets/share-icon.png', renderShareCard()],
  [
    'miniapp/src/lib/logo.ts',
    [
      '/* 自动生成, 请勿手改: node scripts/gen_logo.mjs (几何定义在 scripts/gen_logo.mjs) */',
      '/* 小程序里不用 <Image src="xxx.svg">: base64 PNG 在 iOS/Android 上表现最稳, 且不需要配 loader */',
      `export const LOGO_MARK_DATA_URI = 'data:image/png;base64,${renderMark(96, 'default').toString('base64')}'`,
      '',
    ].join('\n'),
  ],
]

const check = process.argv.includes('--check')
let failed = false

for (const [relative, content] of targets) {
  const absolute = resolve(repoRoot, relative)
  const isBinary = Buffer.isBuffer(content)
  const current = existsSync(absolute) ? readFileSync(absolute, isBinary ? undefined : 'utf8') : null
  const same = isBinary ? current?.equals(content) : current === content
  if (check) {
    if (!same) {
      failed = true
      console.error(`✗ ${relative} 与 scripts/gen_logo.mjs 不一致, 请运行: node scripts/gen_logo.mjs`)
    } else {
      console.log(`✓ ${relative}`)
    }
    continue
  }
  mkdirSync(dirname(absolute), { recursive: true })
  writeFileSync(absolute, content)
  console.log(`写入 ${relative}${isBinary ? ` (${content.length} 字节)` : ''}`)
}

if (check && failed) process.exit(1)
