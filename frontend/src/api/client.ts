import axios, { AxiosError, AxiosRequestConfig } from 'axios'
import type { ApiEnvelope } from '../types'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  // 生成任务已改为异步, 常规请求不需要长超时
  timeout: 30000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

const LOGIN_PATH = '/login'
let refreshing: Promise<unknown> | null = null

/**
 * 这几个端点返回 401 时**不要**去刷新令牌:
 *   - `/auth/refresh` 自己失败就是刷新失败, 再刷一次只会死循环
 *   - 登录类接口的 401 是业务结果 (账号/密码不对), 不是"令牌过期"
 *
 * ⚠ 之前这里写的是 `!url.includes('/auth/')`, 于是 `/auth/me` 的 401 也被排除在
 *   续期之外 —— 登录超过 2 小时后点任意 Tab, App 会重新拉 `fetchCurrentUser()`,
 *   拿到 401 就直接被踢到登录页, 明明 refresh cookie 还有效却没机会用。
 */
const NO_REFRESH_URLS = ['/auth/refresh', '/auth/login', '/auth/dev-login']
const isNoRefreshUrl = (url: string) => NO_REFRESH_URLS.some((path) => url.includes(path))

/** 未授权时的跳转方式, 由 App 注入 SPA 内导航; 没注入就退回整页跳转 */
type UnauthorizedHandler = (target: string) => void
let unauthorizedHandler: UnauthorizedHandler | null = null

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

function redirectToLogin() {
  if (window.location.pathname === LOGIN_PATH) return
  const target = `${LOGIN_PATH}?redirect=${encodeURIComponent(
    window.location.pathname + window.location.search,
  )}`
  // 优先走 SPA 内跳转: window.location.assign 会整页刷新, 把正在轮询的生成任务
  // (useGenerationStore) 一起冲掉 —— 生成要 1-2 分钟, 等于白等
  if (unauthorizedHandler) {
    unauthorizedHandler(target)
    return
  }
  window.location.assign(target)
}

apiClient.interceptors.response.use(
  (response) => response.data,
  async (error: AxiosError) => {
    const status = error.response?.status
    const config = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined
    const url = config?.url || ''

    if (status === 401 && config && !config._retry && !isNoRefreshUrl(url)) {
      config._retry = true
      try {
        refreshing = refreshing ?? apiClient.post('/auth/refresh')
        await refreshing
        refreshing = null
        return apiClient.request(config)
      } catch {
        // 刷新失败才算真的没登录; 后面的 if 会负责跳转
        refreshing = null
      }
    }
    if (status === 401 && !isNoRefreshUrl(url)) {
      redirectToLogin()
    }
    return Promise.reject(normalizeError(error))
  },
)

/** 把后端的错误信封 / FastAPI 校验错误统一成可读文案 */
export function normalizeError(error: unknown): Error {
  const axiosError = error as AxiosError<Record<string, unknown>>
  const payload = axiosError?.response?.data
  if (payload) {
    const message = payload.message ?? payload.detail ?? payload.error
    if (typeof message === 'string' && message) return new Error(message)
    if (Array.isArray(message) && message.length > 0) {
      const first = message[0] as { msg?: string }
      if (first?.msg) return new Error(first.msg)
    }
  }
  if (axiosError?.message) return new Error(axiosError.message)
  return new Error('请求失败, 请稍后重试')
}

/** 从统一信封中取出业务数据 */
export async function unwrap<T>(request: Promise<unknown>): Promise<T> {
  const envelope = (await request) as ApiEnvelope<T>
  return envelope?.data as T
}

export default apiClient
