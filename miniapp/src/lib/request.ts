/**
 * 请求层 - Taro.request + Bearer 令牌 + 401 自动续期
 *
 * 返回的是**解包后**的业务数据 (信封里的 data), 出错时抛 Error(可读文案),
 * 与 H5 的 axios 拦截器行为保持一致, 页面里只需要 try/catch 一个 Error。
 */
import Taro from '@tarojs/taro'

import { ENDPOINTS } from '@shared/endpoints'
import type { ApiEnvelope } from '@shared/types'

import { clearSession, getAccessToken, getRefreshToken, saveSession } from './session'

/** 由 config/dev.ts / config/prod.ts 注入 */
const BASE_URL = typeof API_BASE_URL === 'string' ? API_BASE_URL : 'http://127.0.0.1:8000/api'

const TIMEOUT = 20000

let refreshing: Promise<boolean> | null = null

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** 把后端各种错误形状统一成一句能直接显示给用户的话 */
function normalizeError(status: number, payload: unknown): ApiError {
  const body = (payload || {}) as Record<string, unknown>
  const raw = body.detail ?? body.message ?? body.error
  if (typeof raw === 'string' && raw) return new ApiError(raw, status)
  if (Array.isArray(raw) && raw.length > 0) {
    const first = raw[0] as { msg?: string }
    if (first?.msg) return new ApiError(first.msg, status)
  }
  if (status === 401) return new ApiError('登录状态已失效, 请重新登录', status)
  if (status === 429) return new ApiError('今天生成得有点多, 明天再来试试', status)
  if (status >= 500) return new ApiError('服务开小差了, 请稍后重试', status)
  return new ApiError(`请求失败 (${status})`, status)
}

function redirectToLogin(): void {
  clearSession()
  const pages = Taro.getCurrentPages()
  const current = pages[pages.length - 1]?.route || ''
  if (current.includes('pages/login')) return
  Taro.reLaunch({ url: '/pages/login/index' })
}

/** 刷新令牌 (小程序走 body, 不走 Cookie) */
async function refreshSession(): Promise<boolean> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return false
  try {
    const response = await Taro.request({
      url: `${BASE_URL}${ENDPOINTS.authRefresh}`,
      method: 'POST',
      data: { refresh_token: refreshToken },
      timeout: TIMEOUT,
      header: { 'Content-Type': 'application/json' },
    })
    const envelope = response.data as ApiEnvelope<Record<string, unknown>>
    if (response.statusCode >= 400 || !envelope?.data?.access_token) return false
    saveSession(envelope.data as never)
    return true
  } catch {
    return false
  }
}

/** Taro.request 的返回形状 (只取我们真正用到的两个字段) */
interface RawResponse {
  statusCode: number
  data: unknown
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data?: Record<string, unknown> | undefined
  /** 401 时不跳登录页 (登录相关接口自己处理) */
  skipAuthRedirect?: boolean
  /** AbortSignal: 切页面时 abort 未完成的旧请求, 消除 setState on unmounted 警告 */
  signal?: AbortSignal | null
}

async function send<T>(path: string, options: RequestOptions = {}, retry = true): Promise<T> {
  const token = getAccessToken()
  const header: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) header.Authorization = `Bearer ${token}`

  // Taro.request 4.0+ 支持 signal 参数; 老基础库/旧 H5 构建忽略即可
  const signal: AbortSignal | undefined = options.signal ?? undefined
  if (signal?.aborted) {
    throw new ApiError('请求已取消', 0)
  }

  let response: RawResponse
  try {
    response = (await Taro.request({
      url: `${BASE_URL}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header,
      timeout: TIMEOUT,
      signal,
    })) as unknown as RawResponse
  } catch (err) {
    // 用户主动取消: 静默吞掉, 不弹 toast
    if (signal?.aborted || (err as { errMsg?: string })?.errMsg?.includes('abort')) {
      throw new ApiError('请求已取消', 0)
    }
    throw new ApiError('网络连接失败, 请检查网络后重试', 0)
  }

  const { statusCode } = response

  if (statusCode === 401 && retry && !path.includes(ENDPOINTS.authRefresh)) {
    refreshing = refreshing || refreshSession()
    const ok = await refreshing
    refreshing = null
    if (ok) return send<T>(path, options, false)
    if (!options.skipAuthRedirect) redirectToLogin()
    throw normalizeError(statusCode, response.data)
  }

  if (statusCode >= 400) {
    if (statusCode === 401 && !options.skipAuthRedirect) redirectToLogin()
    throw normalizeError(statusCode, response.data)
  }

  const envelope = response.data as ApiEnvelope<T>
  return (envelope?.data ?? null) as T
}

export const http = {
  get: <T>(path: string, options?: RequestOptions) => send<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, data?: Record<string, unknown>, options?: RequestOptions) =>
    send<T>(path, { ...options, method: 'POST', data }),
  put: <T>(path: string, data?: Record<string, unknown>, options?: RequestOptions) =>
    send<T>(path, { ...options, method: 'PUT', data }),
  del: <T>(path: string, options?: RequestOptions) =>
    send<T>(path, { ...options, method: 'DELETE' }),
}

export { BASE_URL }
export default http
