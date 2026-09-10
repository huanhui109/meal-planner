import React, { useEffect, useState } from 'react'
import { Alert, Divider, Input, Spin } from 'antd'
import { devLogin, getAuthProviders, getFeishuLoginUrl } from '../api/auth'
import { LogoMark, PillButton } from '../components/ui'
import { brand } from '@shared/brand'
import type { AuthProviders } from '../types'

const DEV_LOGIN_HINT = '本地开发登录仅供调试, 生产环境请关闭 APP__AUTH__DEV_LOGIN'

function redirectTarget(): string {
  return new URLSearchParams(window.location.search).get('redirect') || '/'
}

const Login: React.FC = () => {
  const [providers, setProviders] = useState<AuthProviders | null>(null)
  const [probing, setProbing] = useState(true)
  const [loading, setLoading] = useState(false)
  const [devName, setDevName] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const loginError = params.get('login_error')
    if (loginError) {
      setError(loginError)
      params.delete('login_error')
      const query = params.toString()
      window.history.replaceState({}, '', `${window.location.pathname}${query ? `?${query}` : ''}`)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    getAuthProviders()
      .then((result) => {
        if (!cancelled) setProviders(result)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setProbing(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleFeishuLogin = async () => {
    setLoading(true)
    try {
      const { authorize_url } = await getFeishuLoginUrl(redirectTarget())
      window.location.assign(authorize_url)
    } catch (err) {
      setError((err as Error).message || '无法获取飞书授权地址')
      setLoading(false)
    }
  }

  const handleDevLogin = async () => {
    setLoading(true)
    try {
      await devLogin(devName.trim() || '本地开发用户')
      window.location.assign(redirectTarget())
    } catch (err) {
      setError((err as Error).message || '本地开发登录失败')
      setLoading(false)
    }
  }

  const renderBody = () => {
    if (probing) {
      return (
        <div style={{ padding: '18px 0', textAlign: 'center' }}>
          <Spin />
          <div className="login-hint">正在检查登录方式…</div>
        </div>
      )
    }

    if (!providers) {
      return (
        <Alert
          type="error"
          showIcon
          message="无法获取登录方式"
          description={
            <span>
              {error || '请求 /api/auth/providers 失败。'}
              <br />
              请确认后端已启动（默认 <code>http://127.0.0.1:8000</code>），
              再执行 <code>bash scripts/service.sh health</code> 查看原因。
            </span>
          }
        />
      )
    }

    if (!providers.feishu && !providers.dev_login) {
      return (
        <Alert
          type="warning"
          showIcon
          message="没有可用的登录方式"
          description={
            <span>
              要么在 <code>.env</code> 里配置飞书应用（FEISHU_APP_ID / FEISHU_APP_SECRET /
              APP__FEISHU__REDIRECT_URI），要么开启本地开发登录
              （APP__AUTH__DEV_LOGIN=true）。改完 <code>.env</code> 必须重启后端才会生效。
              详见 docs/local-setup.md。
            </span>
          }
        />
      )
    }

    return (
      <>
        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            style={{ marginBottom: 16 }}
            closable
            onClose={() => setError('')}
          />
        )}

        {providers.feishu && (
          <>
            <PillButton block loading={loading} onClick={handleFeishuLogin}>
              使用飞书扫码登录
            </PillButton>
            <div className="login-hint">电脑端展示二维码, 手机端自动打开飞书完成授权</div>
          </>
        )}

        {providers.feishu && providers.dev_login && (
          <Divider plain style={{ margin: '20px 0 14px', fontSize: 12 }}>
            或
          </Divider>
        )}

        {providers.dev_login && (
          <>
            <Input
              placeholder="输入昵称即可进入 (不同昵称 = 不同用户)"
              value={devName}
              maxLength={20}
              size="large"
              onChange={(event) => setDevName(event.target.value)}
              onPressEnter={handleDevLogin}
            />
            <div style={{ marginTop: 10 }}>
              <PillButton variant="gray" block loading={loading} onClick={handleDevLogin}>
                本地开发登录
              </PillButton>
            </div>
            <div className="login-hint">{DEV_LOGIN_HINT}</div>
          </>
        )}
      </>
    )
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <LogoMark size={56} className="login-mark" />
        <div className="login-title">{brand.name}</div>
        <div className="login-sub">{brand.slogan}</div>
        <div className="login-body">{renderBody()}</div>
      </div>
    </div>
  )
}

export default Login
