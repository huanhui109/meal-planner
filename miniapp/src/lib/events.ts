/**
 * 埋点 SDK (audit T2.6) - 内存缓冲 + 定时 flush
 *
 * 设计:
 * 1. 调 track(name, props) 不立即上报, 先入队; 满 10 条 / 满 30s / unload 触发 flush
 * 2. 后端接受 batch 上报, 单批 <= 50 条 (BATCH_LIMIT)
 * 3. 失败不抛异常 / 不弹 toast, 内部 counter 标记后丢弃 (业务优先)
 * 4. flush 内部用 fire-and-forget, 不阻塞调用方
 * 5. 小程序卸载 (onHide) 时手动 flush 一次防止丢数据 (Taro.onAppHide 钩子)
 */
import Taro from '@tarojs/taro'

import { reportEvents } from './api'

interface PendingEvent {
  event_name: string
  ts: number
  properties?: Record<string, unknown>
  app_version?: string
  platform?: string
}

const QUEUE_KEY = 'mp:events:queue:v1'
const FLUSH_INTERVAL_MS = 30_000
const SIZE_LIMIT = 10
const BATCH_LIMIT = 50
const MAX_QUEUE_LENGTH = 200 // 防止极端情况下无限增长

let queue: PendingEvent[] = []
let timer: ReturnType<typeof setInterval> | null = null
let failedDrops = 0
let appVersionCached: string | null = null

function readCachedQueue(): void {
  try {
    const raw = Taro.getStorageSync(QUEUE_KEY) as string | null
    if (raw) {
      const parsed = JSON.parse(raw) as PendingEvent[]
      if (Array.isArray(parsed)) queue = parsed.slice(-MAX_QUEUE_LENGTH)
    }
  } catch {
    /* ignore */
  }
}

function persistQueue(): void {
  try {
    Taro.setStorageSync(QUEUE_KEY, JSON.stringify(queue.slice(-MAX_QUEUE_LENGTH)))
  } catch {
    /* ignore quota */
  }
}

function getAppVersion(): string {
  if (appVersionCached !== null) return appVersionCached
  try {
    const app = Taro.getApp?.() as { version?: string } | undefined
    appVersionCached = app?.version || 'unknown'
  } catch {
    appVersionCached = 'unknown'
  }
  return appVersionCached
}

function getPlatform(): string {
  // Taro.getEnv() 返回 ENV_TYPE 字面量 ('WEAPP' | 'H5' | ...), 编译期就已知, 直接当作值
  try {
    const env = Taro.getEnv?.() as unknown as string | undefined
    const lower = (env || '').toLowerCase()
    if (lower === 'weapp' || lower === 'h5') return lower
  } catch {
    /* fallthrough */
  }
  // 兜底: 开发器判断不到时, 看 systemInfo 里 platform
  try {
    const info = Taro.getSystemInfoSync()
    const p = (info.platform || '').toLowerCase()
    if (p.includes('devtools') || p.includes('ios') || p.includes('android')) {
      // 在这些场景里小程序通常走 weapp 通道, H5 走 webview
      return Taro.getEnv?.() ? 'weapp' : 'h5'
    }
  } catch {
    /* ignore */
  }
  return 'unknown'
}

async function flush(reason: 'size' | 'interval' | 'manual' | 'unload'): Promise<void> {
  if (queue.length === 0) return
  const batch = queue.slice(0, BATCH_LIMIT)
  try {
    await reportEvents(batch)
    // 成功: 把 batch 从队列首部弹出
    queue.splice(0, batch.length)
    persistQueue()
  } catch {
    // 失败: 把这批留回队首, 计数一次, 避免无限重试拖垮网络
    failedDrops += 1
    if (failedDrops > 3) {
      // 连续 3 次失败, 丢弃队列前 50 条防止长期堆积
      queue.splice(0, Math.min(50, queue.length))
      failedDrops = 0
    }
    persistQueue()
    // 不弹 toast, 不打 console.error (埋点跟业务隔离)
    if (process.env.NODE_ENV !== 'production') {
      // 仅调试可见
      Taro.getStorageSync(QUEUE_KEY) // no-op just to keep the linter quiet in some setups
    }
  }
  // flush drain 重入: 如果上一批 flush 后剩余仍 >= SIZE_LIMIT, 继续冲
  if (reason === 'size' && queue.length >= SIZE_LIMIT) {
    void flush('size')
  }
}

function startTimer(): void {
  if (timer) return
  timer = setInterval(() => {
    void flush('interval')
  }, FLUSH_INTERVAL_MS)
}

/**
 * 启动 SDK:
 *  - 读上次未上报的队列 (跨启动期不丢数据)
 *  - 起定时 flush
 *  - 监听 Taro.onAppHide / onPageUnload (小程序特有), 触发最后一次 flush
 */
export function initEvents(): void {
  readCachedQueue()
  startTimer()
  try {
    Taro.onAppHide(() => {
      // 进入后台时立马冲一次 (后面再回前台也不会丢)
      void flush('unload')
    })
  } catch {
    /* Taro H5 build 不提供 onAppHide, 跳过 */
  }
}

export function track(eventName: string, properties?: Record<string, unknown>): void {
  if (!eventName) return
  const item: PendingEvent = {
    event_name: eventName,
    ts: Date.now(),
    properties: properties || undefined,
    app_version: getAppVersion(),
    platform: getPlatform(),
  }
  queue.push(item)
  // 超长截断
  if (queue.length > MAX_QUEUE_LENGTH) {
    queue.splice(0, queue.length - MAX_QUEUE_LENGTH)
  }
  persistQueue()
  if (queue.length >= SIZE_LIMIT) {
    void flush('size')
  }
}

/** 主动冲一次 (用户登出 / 测试按钮时使用) */
export async function flushEvents(): Promise<void> {
  await flush('manual')
}

/** 当前队列长度 (调试面板用) */
export function pendingEventCount(): number {
  return queue.length
}
