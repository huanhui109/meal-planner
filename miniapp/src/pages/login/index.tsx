/**
 * 登录页
 *
 * 优先级: 微信一键登录 (真实用户) > 本地开发登录 (开发期, 后端需开 APP__AUTH__DEV_LOGIN)。
 * 两者后端都返回同样的令牌组, 存进 storage 后所有请求带 Authorization: Bearer。
 */
import { useCallback, useEffect, useState } from 'react'
import { Image, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { brand } from '@shared/brand'
import type { AuthProviders } from '@shared/types'

import { Banner, LoadingStack, PillButton } from '../../components/ui'
import { devLogin, getAuthProviders, wechatMiniLogin } from '../../lib/api'
import { track } from '../../lib/events'
import { getCachedUser, isLoggedIn, saveSession } from '../../lib/session'
import { LOGO_MARK_DATA_URI, LOGO_MARK_DATA_URI_DARK } from '../../lib/logo'
import { useTheme } from '../../lib/theme'

export default function LoginPage() {
  const [providers, setProviders] = useState<AuthProviders | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [theme, , applied] = useTheme()
  // 暗色 / 明亮 UI 配 inverse (白容框), 冷色 UI 配 default (深容框), 与 H5 LogoMark 规则一致
  const logoSrc = applied !== 'cool' ? LOGO_MARK_DATA_URI_DARK : LOGO_MARK_DATA_URI

  const enter = useCallback(() => {
    Taro.switchTab({ url: '/pages/today/index' })
  }, [])

  const detect = useCallback(async () => {
    try {
      setProviders(await getAuthProviders())
    } catch (err) {
      setError((err as Error).message)
    }
  }, [])

  useEffect(() => {
    if (isLoggedIn()) {
      enter()
      return
    }
    void detect()
  }, [detect, enter])

  const handleWechatLogin = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await Taro.login()
      if (!result.code) throw new Error('没能拿到微信登录凭证, 请重试')
      const bundle = await wechatMiniLogin(result.code)
      saveSession(bundle)
      track('login', { method: 'wechat' })
      enter()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleDevLogin = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('先写个昵称, 方便区分不同账号')
      return
    }
    setBusy(true)
    setError('')
    try {
      const bundle = await devLogin(trimmed)
      saveSession(bundle)
      track('login', { method: 'dev' })
      enter()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const cached = getCachedUser()

  return (
    <View className="login-page">
      <View className="login-card">
        <Image className="login-logo" src={logoSrc} mode="aspectFit" />
        <Text className="login-title">{brand.name}</Text>
        <View className="login-sub">{brand.fullName}</View>
        <View className="login-desc">{brand.description}</View>

        <View className="login-body">
          {error ? <Banner tone="danger">{error}</Banner> : null}

          {providers === null ? (
            <LoadingStack rows={2} />
          ) : (
            <>
              {providers.wechat ? (
                <PillButton block disabled={busy} onClick={handleWechatLogin}>
                  {busy ? '登录中…' : '微信一键登录'}
                </PillButton>
              ) : (
                <Banner tone="warn">
                  还没配置微信小程序 AppID/AppSecret，所以「微信一键登录」暂时不可用。
                </Banner>
              )}

              {providers.dev_login ? (
                <View style={{ marginTop: 18 }}>
                  <View className="field__label">本地开发登录</View>
                  <Input
                    className="text-input"
                    value={name}
                    placeholder="昵称, 例如 小明"
                    onInput={(event) => setName(event.detail.value)}
                  />
                  <View className="field__hint">
                    仅供开发调试：后端开了 APP__AUTH__DEV_LOGIN 才会出现这个入口，生产环境请关掉。
                  </View>
                  <View style={{ marginTop: 12 }}>
                    <PillButton block variant="gray" disabled={busy} onClick={handleDevLogin}>
                      {busy ? '登录中…' : '用这个昵称进入'}
                    </PillButton>
                  </View>
                </View>
              ) : null}

              {!providers.wechat && !providers.dev_login ? (
                <View className="field__hint" style={{ marginTop: 12 }}>
                  当前没有可用的登录方式：请在小程序后台配置 AppID/AppSecret，或让后端打开本地开发登录。
                </View>
              ) : null}
            </>
          )}
        </View>

        {cached ? (
          <View className="field__hint" style={{ marginTop: 16 }}>
            上次登录：{cached.name}
          </View>
        ) : null}
      </View>
    </View>
  )
}
