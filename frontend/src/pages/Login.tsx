import React, { useEffect, useState } from 'react'
import { Alert, Button, Divider, Input, Spin, Typography, message } from 'antd'
import { devLogin, getAuthProviders, getFeishuLoginUrl } from '../api/auth'
import type { AuthProviders } from '../types'

const DEV_LOGIN_HINT = '本地开发登录仅供本地调试使用, 生产环境请关闭 APP__AUTH__DEV_LOGIN'

function redirectTarget(): string {
  return new URLSearchParams(window.location.search).get('redirect') || '/'
}

const Login: React.FC = () => {
  const [providers, setProviders] = useState<AuthProviders | null>(null)
  const [probing, setProbing] = useState(true)
  const [loading, setLoading] = useState(false)
  const [devName, setDevName] = useState('')
  const [error, setError] = useState('')
  const [showError, setShowError] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const loginError = params.get('login_error')
    if (loginError) {
      setError(loginError)
      setShowError(true)
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
        if (!cancelled) {
          setError(err.message)
          setShowError(true)
        }
      })
      .finally(() => {
        if (!cancelled) setProbing(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const fail = (err: unknown, fallback: string) => {
    const text = (err as Error).message || fallback
    setError(text)
    setShowError(true)
    message.error(text)
    setLoading(false)
  }

  const handleFeishuLogin = async () => {
    setLoading(true)
    try {
      const { authorize_url } = await getFeishuLoginUrl(redirectTarget())
      window.location.assign(authorize_url)
    } catch (err) {
      fail(err, '无法获取飞书授权地址')
    }
  }

  const handleDevLogin = async () => {
    setLoading(true)
    try {
      await devLogin(devName.trim() || '本地开发用户')
      window.location.assign(redirectTarget())
    } catch (err) {
      fail(err, '本地开发登录失败')
    }
  }

  const renderBody = () => {
    if (probing) return <Spin tip="正在检查登录方式..." />
    if (!providers || (!providers.feishu && !providers.dev_login)) {
      return (
        <Alert
          type="warning"
          showIcon
          message="没有可用的登录方式"
          description={
            <span>
              要么在 <code>.env</code> 里配置飞书应用（FEISHU_APP_ID / FEISHU_APP_SECRET /
              APP__FEISHU__REDIRECT_URI），要么开启本地开发登录
              （APP__AUTH__DEV_LOGIN=true）。详见 docs/local-setup.md。
            </span>
          }
        />
      )
    }
    return (
      <>
        {providers.feishu && (
          <>
            <Button
              type="primary"
              size="large"
              block
              loading={loading}
              onClick={handleFeishuLogin}
            >
              使用飞书扫码登录
            </Button>
            <div className="login-hint">
              电脑端将展示二维码, 手机端会自动打开飞书完成授权
            </div>
          </>
        )}

        {providers.feishu && providers.dev_login && (
          <Divider plain style={{ margin: '22px 0 16px', fontSize: 12 }}>
            或
          </Divider>
        )}

        {providers.dev_login && (
          <div className="login-dev">
            <Input
              placeholder="输入一个昵称 (不同昵称即不同用户)"
              value={devName}
              maxLength={20}
              onChange={(event) => setDevName(event.target.value)}
              onPressEnter={handleDevLogin}
              disabled={loading}
            />
            <Button block style={{ marginTop: 10 }} loading={loading} onClick={handleDevLogin}>
              本地开发登录
            </Button>
            <div className="login-hint">{DEV_LOGIN_HINT}</div>
          </div>
        )}
      </>
    )
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-emoji">🍳</div>
        <Typography.Title level={3} style={{ marginBottom: 4 }}>
          每周营养菜谱
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
          AI 根据你的偏好、营养目标与预算, 自动生成一周菜单与采购清单
        </Typography.Paragraph>

        {showError && (
          <Alert
            type="error"
            showIcon
            message={error}
            closable
            onClose={() => setShowError(false)}
            style={{ marginBottom: 16, textAlign: 'left' }}
          />
        )}

        {renderBody()}
      </div>
    </div>
  )
}

export default Login
