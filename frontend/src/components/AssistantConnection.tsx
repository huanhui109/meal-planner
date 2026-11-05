import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Modal, Popconfirm } from 'antd'
import {
  CopyOutlined, DisconnectOutlined, DownloadOutlined, LinkOutlined,
  LoadingOutlined, PlusOutlined, ReloadOutlined,
} from '@ant-design/icons'
import type { AssistantGrant, WorkBuddyStatus } from '@shared/meal'
import {
  authorizeWorkBuddy, createAssistantGrant, disconnectWorkBuddy,
  getAssistantGrants, getWorkBuddyStatus, revokeAssistantGrant,
} from '../api/meals'
import { copyText } from '../lib/clipboard'
import { authorizationTarget, grantState } from '../lib/assistantConnection'

type ConnectionMode = 'workbuddy' | 'skill'
type Action = 'authorize' | 'create' | 'disconnect' | `revoke:${string}`

export default function AssistantConnection() {
  const [params, setParams] = useSearchParams()
  const [status, setStatus] = useState<WorkBuddyStatus | null>(null)
  const [grants, setGrants] = useState<AssistantGrant[]>([])
  const [checking, setChecking] = useState(true)
  const [statusError, setStatusError] = useState('')
  const [grantsError, setGrantsError] = useState('')
  const [action, setAction] = useState<Action | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<ConnectionMode>('skill')
  const [secret, setSecret] = useState('')
  const [copied, setCopied] = useState(false)
  const mounted = useRef(false)
  const generation = useRef(0)
  const grantsVersion = useRef(0)
  const actionLock = useRef(false)
  const outcome = params.get('workbuddy')

  const load = useCallback(async () => {
    const current = ++generation.current
    const version = grantsVersion.current
    setChecking(true)
    const valid = () => mounted.current && current === generation.current
    // A failed host check must not hide usable Skill credentials.
    await Promise.all([
      getWorkBuddyStatus().then((next) => {
        if (valid()) { setStatus(next); setStatusError('') }
      }).catch((err: Error) => {
        if (valid()) { setStatus(null); setStatusError(err.message) }
      }),
      getAssistantGrants().then((next) => {
        if (valid() && version === grantsVersion.current) { setGrants(next); setGrantsError('') }
      }).catch((err: Error) => {
        if (valid() && version === grantsVersion.current) setGrantsError(err.message)
      }),
    ])
    if (valid()) setChecking(false)
  }, [])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => { mounted.current = false; generation.current += 1 }
  }, [load])

  const perform = async (kind: Action, task: () => Promise<void>) => {
    if (actionLock.current) return
    actionLock.current = true
    setAction(kind); setError('')
    try { await task() }
    catch (err) { if (mounted.current) setError((err as Error).message) }
    finally {
      actionLock.current = false
      if (mounted.current) setAction(null)
    }
  }
  const create = () => perform('create', async () => {
    try {
      const { token, ...created } = await createAssistantGrant()
      if (!mounted.current) return
      grantsVersion.current += 1
      setGrantsError('')
      setSecret(token); setCopied(false)
      setGrants((previous) => [created, ...previous.filter((grant) => grant.id !== created.id)])
    } catch (err) {
      // A lost POST response may have created a grant. Never retry automatically.
      void load()
      throw new Error(`${(err as Error).message}。若列表出现未取得凭据的连接，请撤销后重新创建。`)
    }
  })
  const authorize = () => perform('authorize', async () => {
    const { url } = await authorizeWorkBuddy()
    if (mounted.current) window.location.assign(authorizationTarget(url))
  })
  const disconnect = () => perform('disconnect', async () => {
    await disconnectWorkBuddy()
    if (!mounted.current) return
    setStatus(null)
    void load()
  })
  const revoke = (id: string) => perform(`revoke:${id}`, async () => {
    await revokeAssistantGrant(id)
    if (!mounted.current) return
    grantsVersion.current += 1
    setGrants((previous) => previous.map((grant) =>
      grant.id === id ? { ...grant, revoked_at: new Date().toISOString() } : grant))
  })
  const close = () => {
    if (action) return
    setOpen(false); setSecret(''); setCopied(false); setError('')
  }
  const activeCount = grants.filter((grant) => grantState(grant) === 'active').length
  const hostMessage = checking && !status ? '正在检查网页直发'
    : status?.state === 'not_configured' ? '网页直发未启用，可使用 Skill 连接'
      : status?.message ?? '暂时无法确认网页直发状态'

  return <section id="assistant" className="meal-settings-section">
    <div className="meal-setting-line"><h2>助手连接</h2>
      <button type="button" className="meal-icon" title="刷新连接状态" aria-label="刷新助手连接"
        aria-busy={checking} disabled={checking || Boolean(action)} onClick={() => { void load() }}>
        {checking ? <LoadingOutlined /> : <ReloadOutlined />}
      </button>
    </div>
    {outcome && <Alert type={outcome === 'connected' ? 'success' : 'warning'} showIcon closable
      message={outcome === 'connected' ? 'WorkBuddy 授权完成' : '授权未完成或已过期，请重新连接'}
      onClose={() => {
        const next = new URLSearchParams(params); next.delete('workbuddy'); setParams(next, { replace: true })
      }} />}
    <div className="meal-connection-summary" aria-live="polite">
      <p className="meal-workbuddy-state">
        <span className={`meal-connection-dot ${status?.state === 'online' ? 'online' : ''}`} />
        <span>{hostMessage}</span>
      </p>
      <p className="meal-muted">{activeCount ? `${activeCount} 份有效 Skill 凭据` : '尚无有效 Skill 凭据'}</p>
    </div>
    {statusError && <Alert message={statusError} type="warning" showIcon />}
    {grantsError && <Alert message={`Skill 凭据暂时无法读取：${grantsError}`} type="warning" showIcon />}
    {error && !open && <Alert message={error} type="error" showIcon />}
    <div className="meal-actions">
      <button type="button" className="meal-button meal-primary" disabled={Boolean(action)} onClick={() => {
        setMode(status?.configured ? 'workbuddy' : 'skill'); setError(''); setOpen(true)
      }}><LinkOutlined />连接助手</button>
      {status?.connected && <Popconfirm title="断开网页与 WorkBuddy 的连接？"
        description="正在等待的调整将取消；Skill 凭据不受影响。" okText="断开" cancelText="保留"
        onConfirm={disconnect}>
        <button type="button" className="meal-button" disabled={Boolean(action)}>
          {action === 'disconnect' ? <LoadingOutlined /> : <DisconnectOutlined />}断开网页直连
        </button>
      </Popconfirm>}
    </div>
    <div className="meal-grants">
      {grants.map((grant) => {
        const state = grantState(grant)
        return <div className="meal-grant" key={grant.id}>
          <div><strong>{grant.name}</strong><p>{state === 'revoked' ? '已撤销' : state === 'expired'
            ? '已过期' : `凭据有效至 ${grant.expires_at.slice(0, 10)}`} · Skill</p></div>
          {!grant.revoked_at && <Popconfirm title="撤销此助手的访问权限？" okText="撤销" cancelText="取消"
            onConfirm={() => revoke(grant.id)}>
            <button type="button" className="meal-icon" disabled={Boolean(action)}
              title="撤销凭据" aria-label={`撤销${grant.name}`}>
              {action === `revoke:${grant.id}` ? <LoadingOutlined /> : <DisconnectOutlined />}
            </button>
          </Popconfirm>}
        </div>
      })}
    </div>
    <Modal title={secret ? '保存 Skill 连接凭据' : '连接助手'} open={open} footer={null}
      onCancel={close} closable={!action} maskClosable={!action} keyboard={!action} destroyOnHidden width={540}>
      <div className="meal-form meal-connection-dialog">
        {!secret && <div className="meal-segments meal-connection-modes" role="group" aria-label="助手连接方式">
          {([['workbuddy', '网页直发'], ['skill', 'Skill 连接']] as const).map(([value, label]) =>
            <button type="button" key={value} aria-pressed={mode === value}
              className={mode === value ? 'active' : ''} disabled={Boolean(action)}
              onClick={() => { setMode(value); setError('') }}>{label}</button>)}
        </div>}
        {error && <Alert message={error} type="error" showIcon />}
        {secret ? <>
          <p>凭据仅显示这一次。请在可信终端中运行饭决 Skill 的 connect 命令，在隐藏输入中粘贴；不要发到聊天或日志。</p>
          <label className="meal-field meal-field-stack"><span>服务地址</span>
            <input readOnly value={window.location.origin} /></label>
          <label className="meal-field meal-field-stack"><span>连接凭据</span>
            <input aria-label="连接凭据" type="password" value={secret} readOnly /></label>
          <div className="meal-actions">
            <button type="button" className="meal-button meal-primary" onClick={() => {
              void copyText(secret).then((ok) => {
                setCopied(ok); if (!ok) setError('无法访问剪贴板，请从凭据框手动复制')
              })
            }}><CopyOutlined />{copied ? '已复制' : '复制凭据'}</button>
            <a className="meal-button" href="/api/assistant/skill.zip" download><DownloadOutlined />下载饭决 Skill</a>
            <button type="button" className="meal-button" onClick={close}>完成</button>
          </div>
          <p className="meal-muted">凭据已创建，不代表助手已在线；Skill 连接不启用网页自动发送。</p>
        </> : mode === 'workbuddy' ? <>
          <p>{hostMessage}</p>
          {status?.configured ? <button type="button" className="meal-button meal-primary"
            disabled={Boolean(action)} onClick={() => { void authorize() }}>
            {action === 'authorize' ? <LoadingOutlined /> : <LinkOutlined />}
            {action === 'authorize' ? '正在打开授权' : status.connected ? '重新授权 WorkBuddy' : '授权 WorkBuddy'}
          </button> : <>
            <p className="meal-muted">{status?.configured === false
              ? '网页直发需服务管理员配置 WorkBuddy 应用。Skill 可独立连接，无需这项配置。'
              : '连接状态尚未确认，可重新检查或先使用 Skill 连接。'}</p>
            <div className="meal-actions">
              <button type="button" className="meal-button meal-primary" onClick={() => setMode('skill')}>
                <LinkOutlined />使用 Skill 连接
              </button>
              {!status && <button type="button" className="meal-button" disabled={checking}
                onClick={() => { void load() }}>
                {checking ? <LoadingOutlined /> : <ReloadOutlined />}{checking ? '检查中' : '重新检查'}
              </button>}
            </div>
          </>}
        </> : <>
          <p>授权助手读取这一餐、保存调整建议；不包含确认用餐、下单或扣库存权限。</p>
          <p className="meal-muted">在 WorkBuddy 等助手中使用饭决 Skill。网页需复制任务到助手，不会自动发送。</p>
          {activeCount > 0 && <p className="meal-muted">已有 {activeCount} 份有效凭据；已安装的助手无需重复创建。</p>}
          <div className="meal-actions">
            <button type="button" className="meal-button meal-primary" disabled={Boolean(action)}
              onClick={() => { void create() }}>
              {action === 'create' ? <LoadingOutlined /> : <PlusOutlined />}
              {action === 'create' ? '正在创建凭据' : '创建 Skill 凭据'}
            </button>
            <a className="meal-button" href="/api/assistant/skill.zip" download><DownloadOutlined />下载饭决 Skill</a>
          </div>
        </>}
      </div>
    </Modal>
  </section>
}
