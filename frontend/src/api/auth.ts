import apiClient, { unwrap } from './client'
import type { AuthProviders, CurrentUser } from '../types'

/** 探测可用的登录方式 (飞书扫码 / 本地开发登录) */
export const getAuthProviders = () =>
  unwrap<AuthProviders>(apiClient.get('/auth/providers'))

/** 本地开发登录 (仅当后端 APP__AUTH__DEV_LOGIN=true 时可用) */
export const devLogin = (name: string) =>
  unwrap<CurrentUser>(apiClient.post('/auth/dev-login', { name }))

/** 获取飞书授权页地址 (PC 展示二维码, 手机端唤起飞书) */
export const getFeishuLoginUrl = (redirect: string = '/') =>
  unwrap<{ authorize_url: string; state: string }>(
    apiClient.get('/auth/feishu/login-url', { params: { redirect } }),
  )

/** 当前登录用户, 未登录会抛 401 错误 */
export const fetchCurrentUser = () => unwrap<CurrentUser>(apiClient.get('/auth/me'))

/** 刷新登录态 */
export const refreshSession = () => unwrap<CurrentUser>(apiClient.post('/auth/refresh'))

/** 退出登录 */
export const logout = () => unwrap<null>(apiClient.post('/auth/logout'))
