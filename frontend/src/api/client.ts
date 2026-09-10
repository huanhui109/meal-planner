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

function redirectToLogin() {
  if (window.location.pathname === LOGIN_PATH) return
  const target = `${LOGIN_PATH}?redirect=${encodeURIComponent(
    window.location.pathname + window.location.search,
  )}`
  window.location.assign(target)
}

apiClient.interceptors.response.use(
  (response) => response.data,
  async (error: AxiosError) => {
    const status = error.response?.status
    const config = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined
    const url = config?.url || ''

    if (status === 401 && config && !config._retry && !url.includes('/auth/')) {
      config._retry = true
      try {
        refreshing = refreshing ?? apiClient.post('/auth/refresh')
        await refreshing
        refreshing = null
        return apiClient.request(config)
      } catch {
        refreshing = null
        redirectToLogin()
      }
    }
    if (status === 401 && !url.includes('/auth/refresh')) {
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
