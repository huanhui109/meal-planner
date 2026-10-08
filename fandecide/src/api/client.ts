import type { SuccessEnvelope } from '@/types'

// 极简封装: 只处理「统一信封 + 错误码」。不引 axios, fetch 足够。
// withCredentials 让同源 proxy 回传的会话 cookie 自动带上。

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'GET', credentials: 'include' })
  return unwrap<T>(res)
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  return unwrap<T>(res)
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'PUT',
    credentials: 'include',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  return unwrap<T>(res)
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'DELETE', credentials: 'include' })
  return unwrap<T>(res)
}

async function unwrap<T>(res: Response): Promise<T> {
  let payload: SuccessEnvelope<T>
  try {
    payload = (await res.json()) as SuccessEnvelope<T>
  } catch {
    throw new ApiError(res.status, '接口返回不是合法 JSON')
  }
  // 后端信封: code=0 成功, 非 0 业务错误
  if (payload.code !== 0) {
    throw new ApiError(res.status, payload.message || '请求失败')
  }
  return payload.data
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}
