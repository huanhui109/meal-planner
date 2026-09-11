#!/usr/bin/env node
/**
 * 生成「每周鲜」品牌资源 —— 符号是「平底锅颠荷包蛋」
 *
 *   node scripts/gen_logo.mjs          写入 SVG 与 PNG
 *   node scripts/gen_logo.mjs --check  只校验产物是否与脚本一致 (CI 用)
 *
 * 四个刻意的设计决定:
 *   1. 图形只有一份几何定义 (下面的 PAN_EGG_* 常量), SVG 与 PNG 都从它渲染,
 *      所以矢量和位图不可能画歪。
 *   2. 光栅化不引任何依赖: 用扫描线覆盖度 + 4 倍子采样做抗锯齿, 再用内置 zlib
 *      手写 PNG。这样 CI 里不需要 sharp / canvas / rsvg 之类的原生依赖。
 *   3. 配色全部读 shared/tokens.ts, Logo 不会和设计系统漂移。
 *   4. 保持扁平: 品牌故事里写的是「线条简洁、扁平」, 所以源稿上的几处渐变一律
 *      取中间色压成纯色。这样矢量版和位图版在小尺寸下都干净, 也不会出现
 *      "SVG 有渐变 / PNG 是平涂" 的色差。
 *
 * 几何源文件: assets/logo 之外, 原始造型来自 pan-egg/ 目录下的矢量稿
 * (1024x1024 坐标系); 下面所有常量都按那个坐标系写, 最后统一缩到 96 网格。
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { deflateSync } from 'node:zlib'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..')
const { tokens } = await import(resolve(repoRoot, 'shared/tokens.ts'))
const C = tokens.color
const B = tokens.brand

// ---------------------------------------------------------------------------
// 几何: 先在 1024x1024 的稿子坐标系里描述, 最后乘 K 缩到 96 网格
// ---------------------------------------------------------------------------

const GRID = 96
const S = 1024
const K = GRID / S

/** 容框: 圆角方形 */
const FRAME_RADIUS = 224
/** 容框描边: 稿子上是 x=8 / stroke-width=3 的矩形描边, 展开成 3 宽的环 */
const FRAME_LINE_OUT = 6.5
const FRAME_LINE_IN = 9.5

/** 锅组整体绕 (512,660) 逆时针倾 8°, 作"颠起"姿态 */
const PAN_ROTATE = -8
const PAN_PIVOT = [512, 660]
/** 锅身: 二次曲线兜底 + 顶部直线封口 (视觉上是一道平底锅的侧壁) */
const PAN_BODY = [[262, 648], [512, 806], [762, 648]]
/** 锅沿 / 锅内 */
const PAN_RIM = [512, 648, 250, 52]
const PAN_INNER = [512, 648, 206, 38]
/** 锅柄: 木色圆角条 */
const PAN_HANDLE = [676, 622, 212, 36, 18]

/** 蛋组整体绕 (470,378) 顺时针转 10°, 刚被颠起来 */
const EGG_ROTATE = 10
const EGG_PIVOT = [470, 378]
/** 蛋白: 五段三次贝塞尔围成的不规则形状 (荷包蛋的蛋白边缘本来就不圆) */
const EGG_START = [404, 296]
const EGG_SEGMENTS = [
  [[470, 262], [556, 280], [588, 332]],
  [[636, 356], [628, 420], [582, 444]],
  [[566, 486], [470, 492], [432, 458]],
  [[372, 480], [320, 432], [344, 384]],
  [[352, 344], [372, 316], [404, 296]],
]
/** 蛋黄 / 高光 */
const YOLK = [470, 366, 48]
const YOLK_LIGHT = [454, 350, 15]

/** 右侧两道暖色小弧线: 点出"颠动"的动势 (稿子上是 7 宽的圆头描边) */
const MOTION_ARCS = [
  [[632, 296], [658, 266], [640, 234]],
  [[686, 330], [710, 304], [693, 276]],
]
const MOTION_WIDTH = 7
const MOTION_DOT = [702, 262, 7]

// ---------------------------------------------------------------------------
// 点集工具
// ---------------------------------------------------------------------------

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

function cubicPoints(p0, p1, p2, p3, seg = 20) {
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

/** 二次贝塞尔 (稿子里锅身与动势弧都是 q 指令) */
function quadPoints(p0, c, p1, seg = 24) {
  const points = []
  for (let i = 0; i <= seg; i += 1) {
    const t = i / seg
    const k = 1 - t
    points.push([
      k * k * p0[0] + 2 * k * t * c[0] + t * t * p1[0],
      k * k * p0[1] + 2 * k * t * c[1] + t * t * p1[1],
    ])
  }
  return points
}

/** 一串首尾相接的三次贝塞尔 (蛋白的边缘) */
function cubicChainPoints(start, segments, seg = 20) {
  const points = []
  let from = start
  for (const [c1, c2, to] of segments) {
    const part = cubicPoints(from, c1, c2, to, seg)
    points.push(...(points.length ? part.slice(1) : part))
    from = to
  }
  return points
}

function scalePoints(points, k) {
  return points.map(([x, y]) => [x * k, y * k])
}

function rotatePoints(points, deg, [cx, cy]) {
  const a = (deg * Math.PI) / 180
  const cos = Math.cos(a)
  const sin = Math.sin(a)
  return points.map(([x, y]) => {
    const dx = x - cx
    const dy = y - cy
    return [cx + dx * cos - dy * sin, cy + dx * sin + dy * cos]
  })
}

/** 外圈 + 反向内圈: 扫描线用的是奇偶规则, 这样能挖出一个环 */
function ringPoints(outer, inner) {
  return [...outer, ...inner.slice().reverse()]
}

const unitNormal = (x, y) => {
  const len = Math.hypot(x, y) || 1
  return [x / len, y / len]
}

/**
 * 把折线加粗成可填充的外轮廓
 *
 * 图形里有两处是"描边"而不是"填充": 蛋白的浅灰轮廓和右侧两道动势弧。
 * 光栅器只会填多边形, 所以这里先把描边展开成轮廓 —— SVG 与 PNG 用的是同一份
 * 轮廓, 两边不会有粗细差异。closed=true 时首尾相连, 出来的是一个环。
 */
function strokeOutline(points, width, closed = false, capSeg = 8) {
  const n = points.length
  if (n < 2) return points
  const half = width / 2
  const at = (i) => points[(i + n) % n]
  const left = []
  const right = []
  for (let i = 0; i < n; i += 1) {
    const cur = at(i)
    const hasPrev = closed || i > 0
    const hasNext = closed || i < n - 1
    const prev = hasPrev ? at(i - 1) : null
    const next = hasNext ? at(i + 1) : null
    let tx = 0
    let ty = 0
    if (prev) {
      const [px, py] = unitNormal(cur[0] - prev[0], cur[1] - prev[1])
      tx += px
      ty += py
    }
    if (next) {
      const [nx, ny] = unitNormal(next[0] - cur[0], next[1] - cur[1])
      tx += nx
      ty += ny
    }
    // 切线 (tx,ty) 逆时针转 90° 得到法线
    const [nx, ny] = unitNormal(-ty, tx)
    left.push([cur[0] + nx * half, cur[1] + ny * half])
    right.push([cur[0] - nx * half, cur[1] - ny * half])
  }

  if (closed) return [...left, ...right.reverse()]

  // 开放折线: 两端各补一个半圆 (圆头线帽)
  const arc = (center, fromAngle, sweep) => {
    const out = []
    for (let i = 0; i <= capSeg; i += 1) {
      const a = fromAngle + (sweep * i) / capSeg
      out.push([center[0] + half * Math.cos(a), center[1] + half * Math.sin(a)])
    }
    return out
  }
  const angleOf = (i) => {
    const p = points[i]
    const q = i === 0 ? points[1] : points[i - 1]
    const t = i === 0 ? [q[0] - p[0], q[1] - p[1]] : [p[0] - q[0], p[1] - q[1]]
    const [ux, uy] = unitNormal(t[0], t[1])
    return Math.atan2(ux, uy) // = 法线 (-ty,tx) 的极角, 即切线角 + 90°
  }
  const last = n - 1
  const endAngle = angleOf(last)
  const startAngle = angleOf(0)
  return [
    ...left,
    ...arc(points[last], endAngle, -Math.PI),
    ...right.reverse(),
    ...arc(points[0], startAngle + Math.PI, -Math.PI),
  ]
}

// ---------------------------------------------------------------------------
// 图标分层: 顺序即绘制顺序 (先底后上)
// ---------------------------------------------------------------------------

/** 细节档: SVG 是矢量的, 永远用 full; PNG 按目标像素降级 */
const FULL_DETAIL = { frameLine: true, panInner: true, eggLine: 4, yolkLight: true }
const COMPACT_DETAIL = { frameLine: false, panInner: false, eggLine: 7, yolkLight: false }
const TINY_DETAIL = { frameLine: false, panInner: false, eggLine: 14, yolkLight: false }

function detailFor(size) {
  if (size >= 128) return FULL_DETAIL
  if (size >= 64) return COMPACT_DETAIL
  return TINY_DETAIL
}

/**
 * @param theme  配色
 * @param detail 细节档。注意: 蛋白的描边**不能删** —— 白底的白色蛋白全靠它才看得见,
 *               小尺寸下要把它画粗, 而不是拿掉。真正可以省的是容框描边/锅内/高光。
 */
function panEggLayers(theme, detail = FULL_DETAIL) {
  const layers = []
  const push = (fill, points, alpha = 1) => {
    if (!fill) return
    layers.push({ fill, points, alpha })
  }

  // 容框
  push(theme.frame, roundRectPoints(0, 0, S, S, FRAME_RADIUS))
  if (detail.frameLine) {
    push(
      theme.frameLine,
      ringPoints(
        roundRectPoints(FRAME_LINE_OUT, FRAME_LINE_OUT, S - FRAME_LINE_OUT * 2, S - FRAME_LINE_OUT * 2, 219),
        roundRectPoints(FRAME_LINE_IN, FRAME_LINE_IN, S - FRAME_LINE_IN * 2, S - FRAME_LINE_IN * 2, 215),
      ),
    )
  }

  // ---- 锅 ----
  const pan = (points) => rotatePoints(points, PAN_ROTATE, PAN_PIVOT)
  const [hx, hy, hw, hh, hr] = PAN_HANDLE
  push(theme.wood, pan(roundRectPoints(hx, hy, hw, hh, hr)))

  const body = quadPoints(PAN_BODY[0], PAN_BODY[1], PAN_BODY[2])
  // 单色版没有深浅可分, 锅身改画成一道环, 靠留白跟锅沿分开
  push(theme.pan, pan(theme.outline ? strokeOutline(body, 22, true) : body))

  if (!theme.outline) {
    const [rx, ry, rrx, rry] = PAN_RIM
    push(theme.panRim, pan(ellipsePoints(rx, ry, rrx, rry, 0)))
    if (detail.panInner) {
      const [ix, iy, irx, iry] = PAN_INNER
      push(theme.panInner, pan(ellipsePoints(ix, iy, irx, iry, 0)))
    }
  }

  // ---- 动势弧 (在蛋后面, 从锅沿右上方甩出来) ----
  for (const [p0, c, p1] of MOTION_ARCS) {
    push(theme.motion, strokeOutline(quadPoints(p0, c, p1, 18), MOTION_WIDTH), 0.9)
  }
  const [dx, dy, dr] = MOTION_DOT
  push(theme.motion, circlePoints(dx, dy, dr), 0.85)

  // ---- 蛋 ----
  const egg = (points) => rotatePoints(points, EGG_ROTATE, EGG_PIVOT)
  const eggShape = cubicChainPoints(EGG_START, EGG_SEGMENTS)
  if (theme.outline) {
    push(theme.egg, egg(strokeOutline(eggShape, 12, true)))
  } else {
    // 先填蛋白再压描边环: 源稿是 stroke 居中在路径上, 这个顺序才能得到同样粗细的视觉边
    push(theme.egg, egg(eggShape))
    push(theme.eggLine, egg(strokeOutline(eggShape, detail.eggLine, true)))
  }
  const [yx, yy, yr] = YOLK
  push(theme.yolk, egg(circlePoints(yx, yy, yr)))
  if (!theme.outline && detail.yolkLight) {
    const [lx, ly, lr] = YOLK_LIGHT
    push(theme.yolkLight, egg(circlePoints(lx, ly, lr)), 0.85)
  }

  // 全部缩到 96 网格
  return layers.map((layer) => ({
    fill: layer.fill,
    alpha: layer.alpha,
    points: scalePoints(layer.points, K),
  }))
}

const THEMES = {
  /**
   * 默认: **深色**圆角方容框 + 浅色锅。给浅色背景用 —— 应用里 logo 基本都贴在白卡片上,
   * 白色容框会直接隐形, 只剩锅和蛋黄飘着; 深色方框才立得住 (旧版 logo 也是深色方底)。
   */
  default: {
    frame: B.frameDark,
    frameLine: null,
    pan: B.panLight,
    panRim: B.panLightRim,
    panInner: B.panLightInner,
    wood: B.wood,
    yolk: B.yolk,
    yolkLight: B.yolkLight,
    motion: B.motion,
    egg: B.egg,
    eggLine: null,
  },
  /** 反白: 白色圆角方容框 + 深色锅, 给深色背景/深色卡片用 */
  inverse: {
    frame: B.frame,
    frameLine: B.frameLine,
    pan: B.pan,
    panRim: B.panRim,
    panInner: B.panInner,
    wood: B.wood,
    yolk: B.yolk,
    yolkLight: B.yolkLight,
    motion: B.motion,
    egg: B.egg,
    eggLine: B.eggLine,
  },
  /** 单色: 无容框, 全白剪影, 给飞书卡片 / 深色底 / 单色印刷用 */
  mono: {
    frame: null,
    frameLine: null,
    outline: true,
    pan: '#ffffff',
    wood: '#ffffff',
    motion: '#ffffff',
    egg: '#ffffff',
    yolk: '#ffffff',
  },
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
  const opacity = layer.alpha < 1 ? ` opacity="${layer.alpha}"` : ''
  return `  <polygon points="${points}" fill="${layer.fill}"${opacity} />`
}

function markSvg(themeName) {
  const layers = panEggLayers(THEMES[themeName])
  return [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96" role="img" aria-label="每周鲜">',
    '  <title>每周鲜</title>',
    ...layers.map(polygonTag),
    '</svg>',
    '',
  ].join('\n')
}

function fullLogoSvg() {
  const layers = panEggLayers(THEMES.default)
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

/** 96 网格里的图层渲染成 size x size 的 PNG; 小尺寸自动进简化档 */
function renderMark(size, themeName) {
  const canvas = new Uint8Array(size * size * 4)
  const scale = size / GRID
  const layers = panEggLayers(THEMES[themeName], detailFor(size))
  for (const layer of layers) {
    paint(
      canvas,
      size,
      size,
      layer.points.map(([x, y]) => [x * scale, y * scale]),
      layer.fill,
      layer.alpha,
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
  for (const layer of panEggLayers(THEMES.default)) {
    paint(
      canvas,
      width,
      height,
      layer.points.map(([x, y]) => [x * scale + offsetX, y * scale + offsetY]),
      layer.fill,
      layer.alpha,
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
  // favicon 也用默认(深色容框)版: 浏览器标签页底色基本是浅色, 白色方框会看不见
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

// --preview <目录>: 导出一套尺寸阶梯 + 明暗两版, 供人工验收。
// 不参与 CI 校验, 换标时用它确认最小档还认得出来。
const previewAt = process.argv.indexOf('--preview')
if (previewAt > -1) {
  const dir = process.argv[previewAt + 1]
  if (!dir) {
    console.error('用法: node scripts/gen_logo.mjs --preview <目录>')
    process.exit(1)
  }
  mkdirSync(resolve(dir), { recursive: true })
  for (const size of [16, 32, 48, 64, 96, 192, 1024]) {
    writeFileSync(resolve(dir, `s${size}.png`), renderMark(size, 'default'))
    writeFileSync(resolve(dir, `d${size}.png`), renderMark(size, 'inverse'))
  }
  writeFileSync(resolve(dir, 'light-256.png'), renderMark(256, 'default'))
  writeFileSync(resolve(dir, 'inverse-256.png'), renderMark(256, 'inverse'))
  writeFileSync(resolve(dir, 'mono-256.png'), renderMark(256, 'mono'))
  console.log(`已导出验收图到 ${dir}`)
}

if (check && failed) process.exit(1)
