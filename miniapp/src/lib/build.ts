/**
 * 启动期版本检查 (小程序) - audit T2.4 F6
 *
 * 流程:
 * 1. 读本地缓存的上一次 BuildInfo; 有就用, 跳过本次启动的网络请求
 * 2. 后台异步 fetch 最新 BuildInfo; 拿到后写入缓存, 下次启动用
 * 3. 拿失败 / 拿到但本版本已够 → 直接返回
 * 4. 当前版本 < min_version:
 *    - force_update=true  → reLaunch 到 update 页
 *    - force_update=false → showModal 提示升级
 *
 * 版本比较: 用 SemVer 数字比较 (0.5.0 → 005000), 仅大版本对齐就能判定
 * 不支持: "0.5.0-beta" 这种 pre-release 字符串 (本项目用三段数字足够)
 */
import Taro from '@tarojs/taro'

import type { BuildInfo } from '@shared/types'

import { getBuildInfo } from './api'

const STORAGE_KEY = 'mp:build-info:v1'
const APP_VERSION_KEY = 'mp:app:version:v1'
/** 上次提醒升级的版本号 - 同一版本不重复弹 */
const LAST_PROMPTED_KEY = 'mp:build-info:last-prompted:v1'

interface CachedBuildInfo extends BuildInfo {
  cached_at: number // Date.now() ms
}

/** 把 "0.5.0" 解析为可比较的数字 */
function parseSemver(version: string): number {
  return version
    .split('.')
    .map((segment) => Number.parseInt(segment, 10) || 0)
    .reduce((acc, num, idx) => acc + num * Math.pow(1000, 2 - idx), 0)
}

function readCache(): CachedBuildInfo | null {
  try {
    const raw = Taro.getStorageSync(STORAGE_KEY) as string | null
    if (!raw) return null
    return JSON.parse(raw) as CachedBuildInfo
  } catch {
    return null
  }
}

function writeCache(info: BuildInfo): void {
  try {
    Taro.setStorageSync(STORAGE_KEY, JSON.stringify({ ...info, cached_at: Date.now() }))
  } catch {
    /* ignore quota */
  }
}

function readAppVersion(): string {
  try {
    return (
      Taro.getStorageSync(APP_VERSION_KEY) ||
      // 首次启动从全局 app.version 取
      (Taro.getApp?.() as { version?: string } | undefined)?.version ||
      ''
    )
  } catch {
    return ''
  }
}

/** 对外给 about 页等主动触发 */
export async function checkForUpdateManual(): Promise<
  | { status: 'up_to_date'; current: string; latest: string }
  | { status: 'optional'; current: string; latest: string; notes: string | null }
  | { status: 'force'; current: string; latest: string; notes: string | null; update_url: string | null }
  | { status: 'error'; message: string }
> {
  try {
    const info = await getBuildInfo()
    writeCache(info)
    return compareAndDecide(info)
  } catch (err) {
    return { status: 'error', message: (err as Error).message || '网络异常' }
  }
}

/** 启动期检查 */
export async function checkBuildOnLaunch(): Promise<void> {
  const cached = readCache()
  if (!cached) {
    // 第一次启动, 必须联网拿; 拿不到也别挡
    try {
      const fresh = await getBuildInfo()
      writeCache(fresh)
      handleDecision(fresh)
    } catch {
      /* ignore - 离线启动不该挡用户 */
    }
    return
  }

  // 同步先用缓存, 后台静默 fetch 一次
  void (async () => {
    try {
      const fresh = await getBuildInfo()
      writeCache(fresh)
      handleDecision(fresh)
    } catch {
      // 后台拉失败不影响主流程
    }
  })()
}

type Decision =
  | { status: 'up_to_date'; current: string; latest: string }
  | { status: 'optional'; current: string; latest: string; notes: string | null }
  | { status: 'force'; current: string; latest: string; notes: string | null; update_url: string | null }

function compareAndDecide(info: BuildInfo): Decision {
  const current = readAppVersion()
  const currentNum = parseSemver(current)
  const minNum = parseSemver(info.min_version)
  if (currentNum >= minNum) {
    return { status: 'up_to_date', current, latest: info.latest_version }
  }

  if (info.force_update) {
    return {
      status: 'force',
      current,
      latest: info.latest_version,
      notes: info.notes,
      update_url: info.update_url,
    }
  }
  return { status: 'optional', current, latest: info.latest_version, notes: info.notes }
}

async function handleDecision(info: BuildInfo): Promise<void> {
  const decision = compareAndDecide(info)
  if (decision.status === 'up_to_date') return

  if (decision.status === 'force') {
    // 强制升级: reLaunch 到 update 页
    Taro.reLaunch({ url: '/pages/update/index' })
    return
  }

  if (decision.status === 'optional') {
    // 同版本不重复弹
    const lastPrompted = Taro.getStorageSync(LAST_PROMPTED_KEY) as string | null
    if (lastPrompted === info.latest_version) return
    Taro.setStorageSync(LAST_PROMPTED_KEY, info.latest_version)
    const confirmed = await Taro.showModal({
      title: '新版本可用',
      content: `当前 v${decision.current}, 最新 v${decision.latest}, 建议升级。\n${decision.notes || '修复问题与体验优化'}`,
      confirmText: '查看更新',
      cancelText: '稍后',
    })
    if (confirmed.confirm && info.update_url) {
      Taro.setClipboardData({ data: info.update_url })
      Taro.showToast({ title: '更新链接已复制', icon: 'success' })
    }
  }
}
