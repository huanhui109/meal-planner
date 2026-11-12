import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Modal, Popconfirm } from 'antd'
import {
  CopyOutlined, DisconnectOutlined, DownloadOutlined, LinkOutlined, LoadingOutlined,
  LoginOutlined, LogoutOutlined, PlusOutlined, ReloadOutlined,
} from '@ant-design/icons'
import type { AssistantGrant, ModelCatalogItem, ModelConnectionStatus, WorkBuddyStatus } from '@shared/meal'
import {
  chooseModel, createAssistantGrant, disconnectWorkBuddy,
  getAssistantGrants, getModelStatus, getWorkBuddyStatus, logoutWorkBuddyAccount,
  pollWorkBuddyLogin, revokeAssistantGrant, startWorkBuddyLogin,
} from '../api/meals'
import { copyText } from '../lib/clipboard'
import { grantState } from '../lib/assistantConnection'

type ConnectionMode = 'workbuddy' | 'skill'
type Action = 'authorize' | 'create' | 'disconnect' | 'logout' | `revoke:${string}`
type LoginRegion = 'cn' | 'global'

/** 轮询间隔；登录上限 ~10 分钟，超时就停止，不在后台无限打请求。 */
const LOGIN_POLL_MS = 3000
const LOGIN_MAX_POLLS = 200

interface LoginWait {
  loginId: string
  region: LoginRegion
  /** 后端下发的授权页地址；只允许 http(s)，否则不渲染成链接 */
  verificationUri: string
}

/** 目录项的展示文案：免费优先，其次显示上游积分倍率（没有就不写价格）。 */
const modelOptionLabel = (item: ModelCatalogItem) =>
  `${item.name}${item.free ? '（免费）' : item.credits ? ` ${item.credits}` : ''}`

/** 只把 http(s) 地址渲染成可点击外链，其它 scheme 一律不渲染。 */
const externalUrl = (value: string) => (/^https?:\/\//i.test(value) ? value : '')

export default function AssistantConnection() {
  const [params, setParams] = useSearchParams()
  const [status, setStatus] = useState<WorkBuddyStatus | null>(null)
  const [modelStatus, setModelStatus] = useState<ModelConnectionStatus | null>(null)
  const [grants, setGrants] = useState<AssistantGrant[]>([])
  const [checking, setChecking] = useState(true)
  const [statusError, setStatusError] = useState('')
  const [modelError, setModelError] = useState('')
  const [grantsError, setGrantsError] = useState('')
  const [action, setAction] = useState<Action | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<ConnectionMode>('skill')
  const [secret, setSecret] = useState('')
  const [copied, setCopied] = useState(false)
  // 模型选择 / 重新登录的独立状态：都不影响既有的 WorkBuddy 与 Skill 区块。
  const [modelSaving, setModelSaving] = useState(false)
  const [modelChoiceError, setModelChoiceError] = useState('')
  const [login, setLogin] = useState<LoginWait | null>(null)
  const [loginStarting, setLoginStarting] = useState<LoginRegion | null>(null)
  const [loginNote, setLoginNote] = useState('')
  const [loginError, setLoginError] = useState('')
  const [loginDone, setLoginDone] = useState('')
  const mounted = useRef(false)
  const generation = useRef(0)
  const grantsVersion = useRef(0)
  const actionLock = useRef(false)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollAttempts = useRef(0)
  const loginRun = useRef(0)
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
      // 模型状态独立守卫：失败只落到 modelError，绝不隐藏已加载的 Skill 凭据。
      getModelStatus().then((next) => {
        if (valid()) { setModelStatus(next); setModelError('') }
      }).catch((err: Error) => {
        if (valid()) { setModelStatus(null); setModelError(err.message) }
      }),
    ])
    if (valid()) setChecking(false)
  }, [])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => {
      mounted.current = false
      generation.current += 1
      // 卸载时一定停掉登录轮询，避免定时器在页面离开后继续打接口。
      loginRun.current += 1
      if (pollTimer.current !== null) {
        clearInterval(pollTimer.current)
        pollTimer.current = null
      }
      pollAttempts.current = 0
    }
  }, [load])

  const stopPolling = () => {
    loginRun.current += 1
    if (pollTimer.current !== null) {
      clearInterval(pollTimer.current)
      pollTimer.current = null
    }
    pollAttempts.current = 0
  }

  const beginPolling = (loginId: string, region: LoginRegion) => {
    stopPolling()
    const ticket = loginRun.current
    const active = () => mounted.current && ticket === loginRun.current
    pollTimer.current = setInterval(() => {
      if (!active()) { stopPolling(); return }
      if (pollAttempts.current >= LOGIN_MAX_POLLS) {
        stopPolling()
        setLogin(null)
        setLoginNote('')
        setLoginError('等待登录超时，请重新发起登录')
        return
      }
      pollAttempts.current += 1
      void pollWorkBuddyLogin(loginId, region).then((next) => {
        if (!active()) return
        if (next.done && next.ok) {
          stopPolling()
          setLogin(null)
          setLoginNote('')
          setLoginDone(`登录完成（${next.nickname || next.account_id || '本机账号'}），已可直连模型`)
          setLoginError('')
          void load()
          return
        }
        if (next.done) {
          stopPolling()
          setLogin(null)
          setLoginNote('')
          setLoginError(next.error || '登录未完成，请重新发起')
          return
        }
        setLoginNote(next.message || '等待你在浏览器完成授权')
      }).catch((err: Error) => {
        if (!active()) return
        // 单次轮询失败不终止流程：如实显示原因，由上面的次数上限兜底。
        setLoginNote(`等待登录结果（${err.message}）`)
      })
    }, LOGIN_POLL_MS)
  }

  const startLogin = (region: LoginRegion) => {
    if (loginStarting) return
    stopPolling()
    setLoginStarting(region)
    setLoginError(''); setLoginDone(''); setLoginNote('')
    void startWorkBuddyLogin(region).then((next) => {
      if (!mounted.current) return
      if (!next.ok || !next.login_id) {
        setLogin(null)
        setLoginError(next.error || '暂时无法发起登录，请稍后重试')
        return
      }
      setLogin({
        loginId: next.login_id, region, verificationUri: externalUrl(next.verification_uri ?? ''),
      })
      setLoginNote('等待你在浏览器完成授权')
      beginPolling(next.login_id, region)
    }).catch((err: Error) => {
      if (mounted.current) setLoginError(err.message)
    }).finally(() => {
      if (mounted.current) setLoginStarting(null)
    })
  }

  const cancelLogin = () => {
    stopPolling()
    setLogin(null)
    setLoginNote('')
  }

  const pickModel = (value: string) => {
    if (modelSaving) return
    setModelSaving(true)
    setModelChoiceError('')
    void chooseModel(value).then((next) => {
      if (!mounted.current) return
      // 先按返回值回填，再整卡刷新，避免下拉框在请求期间显示旧模型。
      setModelStatus((previous) => previous ? {
        ...previous, selected: next.selected, model: next.effective, auto: next.auto, selection_available: true,
      } : previous)
      void load()
    }).catch((err: Error) => {
      // 422（模型不在目录 / 区域非法）只是业务提示：就地显示，不打断整卡。
      if (mounted.current) setModelChoiceError(err.message)
    }).finally(() => {
      if (mounted.current) setModelSaving(false)
    })
  }

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
  // 统一模式改为直接调用本机已登录的 WorkBuddy 模型，OAuth 授权跳转不再是主流程。
  // 官方 OAuth 端点仍保留在服务端，旧调用方可继续使用，但本卡片不再触发它。
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
  const accountRegion: LoginRegion = modelStatus?.region === 'global' ? 'global' : 'cn'
  const logout = () => perform('logout', async () => {
    // 只删本应用自己的本机登录副本；桌面端的登录态不由这里改动。
    await logoutWorkBuddyAccount(accountRegion)
    if (!mounted.current) return
    stopPolling()
    setLogin(null); setLoginNote('')
    setLoginError(''); setLoginDone('')
    setModelStatus(null)
    void load()
  })
  const close = () => {
    if (action) return
    // 关闭弹窗即视为放弃本次登录等待，定时器必须一起停。
    stopPolling()
    setLogin(null); setLoginNote('')
    setOpen(false); setSecret(''); setCopied(false); setError('')
  }
  const activeCount = grants.filter((grant) => grantState(grant) === 'active').length
  const hostMessage = checking && !status ? '正在检查网页直发'
    : status?.state === 'not_configured' ? '网页直发未启用，可使用 Skill 连接'
      : status?.message ?? '暂时无法确认网页直发状态'
  const selectValue = modelStatus?.selected ?? ''
  const catalog = modelStatus?.catalog ?? []
  // 只有后端明确说「不可用」才提示；旧响应缺字段时不误报。
  const selectionStale = modelStatus?.selection_available === false
  // 选中的模型若不在本次目录里，必须补一个 option，否则下拉框会显示空白。
  const selectedOffCatalog = Boolean(selectValue) && !catalog.some((item) => item.id === selectValue)
  const loginHref = login ? login.verificationUri : ''
  // 连接状态指示点：绿 = 本机模型已连上、可直接发起请求；灰 = 未连上/未知。
  // 只在「明确已知」时给绿点，状态未确认时保持灰并如实写出原因。
  const connectedDot = !modelStatus
    ? { online: false, text: '检测中' }
    : modelStatus.available
      ? { online: true, text: '已连接' }
      : { online: false, text: '未连接' }

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
      <p className="meal-muted">本机 WorkBuddy 直连模型：{modelStatus
        ? modelStatus.available
          ? `${modelStatus.region} · ${modelStatus.model}`
          : modelStatus.message
        : modelError ? `暂时无法确认模型状态（${modelError}）` : '正在确认本机模型状态'}</p>
      <p className="meal-muted">{activeCount ? `${activeCount} 份有效 Skill 凭据` : '尚无有效 Skill 凭据'}</p>
    </div>
    <div className="meal-connection-summary">
      <label className="meal-field"><span className="meal-field-label">
        <span className={`meal-connection-dot ${connectedDot.online ? 'online' : ''}`} aria-hidden="true" />
        <span>模型选择</span>
        <span className="meal-muted" aria-live="polite">{connectedDot.text}</span>
      </span>
        <select aria-label="选择模型" value={selectValue}
          disabled={!modelStatus || modelSaving || Boolean(action)}
          onChange={(event) => { pickModel(event.target.value) }}>
          <option value="">自动（优先免费）</option>
          {catalog.map((item) => (
            <option key={item.id} value={item.id}>{modelOptionLabel(item)}</option>))}
          {selectedOffCatalog && <option value={selectValue}>{`${selectValue}（已不在本机目录）`}</option>}
        </select>
      </label>
      {modelChoiceError && <Alert type="warning" showIcon
        message={`模型选择未保存：${modelChoiceError}`} />}
      <p className="meal-muted" aria-live="polite">{modelStatus
        ? `当前使用：${modelStatus.model}${modelStatus.auto ? '（自动，优先免费）' : ''} · 本机目录 ${catalog.length} 个可选模型`
        : '正在确认本机模型状态'}</p>
      {modelSaving && <p className="meal-muted">正在保存模型选择…</p>}
      {selectionStale && <Alert type="warning" showIcon
        message="之前选择的模型已不在本机 WorkBuddy 目录里；可以改回「自动（优先免费）」"
        action={<button type="button" className="meal-button"
          disabled={modelSaving || Boolean(action)} onClick={() => { pickModel('') }}>
          自动（优先免费）</button>} />}
    </div>
    {statusError && <Alert message={statusError} type="warning" showIcon />}
    {modelError && <Alert message={`本机模型状态暂时无法读取：${modelError}`} type="warning" showIcon />}
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
    <div className="meal-connection-summary">
      <p className="meal-muted">{modelStatus && !modelStatus.available
        ? '本机登录态不可用：先完成一次网页授权，应用才能直接调用本机模型；也可以改用 Skill 连接。'
        : '重新登录：本机登录态不可用、或想换一个 WorkBuddy 账号时，点对应版本完成一次网页授权。'}</p>
      <div className="meal-actions">
        <button type="button" className="meal-button"
          disabled={Boolean(action) || Boolean(loginStarting) || login !== null}
          onClick={() => { startLogin('cn') }}>
          {loginStarting === 'cn' ? <LoadingOutlined /> : <LoginOutlined />}国内版登录
        </button>
        <button type="button" className="meal-button"
          disabled={Boolean(action) || Boolean(loginStarting) || login !== null}
          onClick={() => { startLogin('global') }}>
          {loginStarting === 'global' ? <LoadingOutlined /> : <LoginOutlined />}国际版登录
        </button>
        {login && <button type="button" className="meal-button" onClick={cancelLogin}>取消等待</button>}
        <Popconfirm title={`退出本机登录（${accountRegion === 'global' ? '国际版' : '国内版'}）？`}
          description="只删除本应用在本机保存的登录副本（应用不再能直连模型）；WorkBuddy 桌面端仍保持自己的登录状态。"
          okText="退出" cancelText="保留"
          onConfirm={logout}>
          <button type="button" className="meal-button" disabled={Boolean(action)}>
            {action === 'logout' ? <LoadingOutlined /> : <LogoutOutlined />}退出本机登录
          </button>
        </Popconfirm>
      </div>
      <p className="meal-muted">{'「退出本机登录」只移除本应用在本机保存的那份登录副本，'
        + 'WorkBuddy 桌面端自己的登录不受影响。'}</p>
      {login
        ? <div className="meal-login-pending" role="status" aria-live="polite">
          <p className="meal-field-label">
            <LoadingOutlined />
            <span>正在等待{login.region === 'global' ? '国际版' : '国内版'}登录完成</span>
            <span className="meal-connection-dot" aria-hidden="true" />
            <span className="meal-muted">未连接</span>
          </p>
          <p className="meal-muted">
            {loginNote || '等待你在浏览器完成授权'}
            {loginHref ? <> · <a href={loginHref} target="_blank" rel="noreferrer">打开授权页</a></> : null}
          </p>
          <p className="meal-muted">授权窗口没有自动弹出时，点上方的「打开授权页」在浏览器里完成授权；完成后这里会自动变成绿色「已连接」。</p>
        </div>
        : null}
      {loginDone && <Alert type="success" showIcon message={loginDone}
        description="模型选择旁的指示点已变绿；现在可以在这一餐页点「交给 AI 调整」直接发起模型请求。" />}
      {loginError && <Alert type="warning" showIcon message={loginError} />}
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
          <div className="meal-model-status" role="status" aria-live="polite">
            <p><strong>本机 WorkBuddy 直连模型</strong></p>
            <p>{modelStatus
              ? modelStatus.available
                ? `可用 · ${modelStatus.region} · ${modelStatus.model}`
                : `不可用 · ${modelStatus.message}`
              : modelError ? `状态暂不可用：${modelError}` : '正在确认本机模型状态'}</p>
            <p className="meal-muted">应用现在直接调用本机已登录的 WorkBuddy 模型生成方案，
              无需再做 OAuth 授权跳转；在这一餐里点「交给 AI 调整」发送即可。</p>
          </div>
          <div className="meal-actions">
            <button type="button" className="meal-button meal-primary" onClick={() => setMode('skill')}>
              <LinkOutlined />使用 Skill 连接
            </button>
            <button type="button" className="meal-button" disabled={checking}
              onClick={() => { void load() }}>
              {checking ? <LoadingOutlined /> : <ReloadOutlined />}{checking ? '检查中' : '重新检查'}
            </button>
          </div>
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
