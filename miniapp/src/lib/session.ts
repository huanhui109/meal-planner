/**
 * 登录态存储 - 小程序没有 httpOnly Cookie, 令牌只能自己存 storage
 *
 * 与 H5 的差别: H5 走 Cookie (浏览器自动带上), 小程序走 `Authorization: Bearer`。
 * 后端 `_extract_token()` 两条通道都认, 所以服务端不用改。
 */
import Taro from '@tarojs/taro'

import type { CurrentUser } from '@shared/types'

const ACCESS_KEY = 'mp_access_token'
const REFRESH_KEY = 'mp_refresh_token'
const USER_KEY = 'mp_user'

export interface TokenBundle {
  access_token: string
  refresh_token: string
  expires_in: number
  user?: CurrentUser
}

export function getAccessToken(): string {
  return Taro.getStorageSync(ACCESS_KEY) || ''
}

export function getRefreshToken(): string {
  return Taro.getStorageSync(REFRESH_KEY) || ''
}

export function getCachedUser(): CurrentUser | null {
  const raw = Taro.getStorageSync(USER_KEY)
  if (!raw) return null
  try {
    return typeof raw === 'string' ? (JSON.parse(raw) as CurrentUser) : (raw as CurrentUser)
  } catch {
    return null
  }
}

export function saveSession(bundle: TokenBundle): void {
  Taro.setStorageSync(ACCESS_KEY, bundle.access_token)
  Taro.setStorageSync(REFRESH_KEY, bundle.refresh_token)
  if (bundle.user) Taro.setStorageSync(USER_KEY, JSON.stringify(bundle.user))
}

export function saveUser(user: CurrentUser): void {
  Taro.setStorageSync(USER_KEY, JSON.stringify(user))
}

export function isLoggedIn(): boolean {
  return Boolean(getAccessToken())
}

export function clearSession(): void {
  Taro.removeStorageSync(ACCESS_KEY)
  Taro.removeStorageSync(REFRESH_KEY)
  Taro.removeStorageSync(USER_KEY)
}
