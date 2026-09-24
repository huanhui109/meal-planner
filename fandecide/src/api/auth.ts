import { apiGet, apiPost } from './client'
import type { CurrentUser } from '@/types'

// 本地用昵称免密登录 (dev-login), 生产走飞书/微信。
// 登录后会话 cookie 由后端 Set-Cookie 落在本机, 后续请求自动带。

export function devLogin(name: string): Promise<CurrentUser> {
  return apiPost<CurrentUser>('/api/auth/dev-login', { name })
}

export function fetchMe(): Promise<CurrentUser> {
  return apiGet<CurrentUser>('/api/auth/me')
}
