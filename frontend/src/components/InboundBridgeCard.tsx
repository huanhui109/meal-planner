/**
 * 设置页「双向唤醒（新）」卡片 —— 与既有 AssistantConnection 并列, 互不修改。
 *
 * 兼容资产（deprecated）：统一模式后本文件不再被挂载，保留供签名固定向量测试与旧调用方引用；不参与主流程。
 *
 * 职责: 颁发令牌对（密码框一次性显示）、复制连接命令（绝不含令牌）、令牌对状态、
 * /allowlist 枚举数量、最近拒绝记录、/audit、分别撤销 web/assistant、单端轮换。
 *
 * 红线:
 *  - web_token / assistant_token 明文只在一次性 modal 的密码框里出现, 关闭即清空;
 *    助手侧令牌明文绝不写入任何内存态 / 复制命令 / 日志;
 *  - 连接命令只含 --url / --pair-id / --instance-id / --session-id / --version 等非敏感参数;
 *  - 模块默认关闭（服务端 L0/L1 开关）时如实显示「模块未启用」, 不谎称可用。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Modal, Popconfirm } from 'antd'
import {
  CopyOutlined, DisconnectOutlined, LoadingOutlined, PlusOutlined,
  ReloadOutlined, SwapOutlined,
} from '@ant-design/icons'
import { copyText } from '../lib/clipboard'
import {
  getAllowlist, getAudit, revokePair, rotatePair,
  type InboundAllowlist, type InboundAuditRow, type InboundPairIssue,
  type InboundRotateResult, type InboundSide,
} from '../api/inboundBridge'
import { setInboundWebToken, useInboundBridge } from '../hooks/useInboundBridge'

export default function InboundBridgeCard() {
  // 卡片不需要主餐次视图, 只用共享内存态里的 pair 元数据与网页侧令牌
  const noop = useCallback(async () => {}, [])
  const bridge = useInboundBridge(null, noop)

  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [allowlist, setAllowlist] = useState<InboundAllowlist | null>(null)
  const [audit, setAudit] = useState<InboundAuditRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [secret, setSecret] = useState<InboundPairIssue | null>(null)
  const [rotated, setRotated] = useState<InboundRotateResult | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [action, setAction] = useState<string | null>(null)
  const mounted = useRef(false)
  const generation = useRef(0)
  const actionLock = useRef(false)

  const load = useCallback(async () => {
    const ticket = ++generation.current
    setLoading(true)
    try {
      const [al, rows] = await Promise.all([getAllowlist(), getAudit(50)])
      if (!mounted.current || ticket !== generation.current) return
      setAllowlist(al); setAudit(rows); setEnabled(true); setError('')
    } catch (err) {
      if (!mounted.current || ticket !== generation.current) return
      const status = (err as { status?: number }).status
      // 503 = 模块停用（L0/L1 开关默认关闭）; 其它错误如实显示, 不伪装成启用
      setEnabled(false)
      setError(status === 503 ? '双向唤醒模块未启用（服务端开关默认关闭）' : (err as Error).message)
    } finally {
      if (mounted.current && ticket === generation.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => { mounted.current = false; generation.current += 1 }
  }, [load])

  const perform = async (kind: string, task: () => Promise<void>) => {
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
    const result = await bridge.issue() // 内部已把非敏感元数据 + 网页侧令牌写入内存
    if (!mounted.current) return
    setSecret(result); setRotated(null); setCopied(null)
    await load()
  })

  const rotate = (side: InboundSide) => perform(`rotate:${side}`, async () => {
    const id = bridge.pair?.pair_id
    if (!id) throw new Error('本次会话尚未颁发令牌对，无法定位连接')
    const result = await rotatePair(id, side)
    // 轮换网页侧后更新内存中的网页侧令牌, 供触发弹窗签名使用
    if (side === 'web') setInboundWebToken(result.token)
    if (!mounted.current) return
    setRotated(result); setSecret(null); setCopied(null)
    await load()
  })

  const revoke = (side: InboundSide) => perform(`revoke:${side}`, async () => {
    const id = bridge.pair?.pair_id
    if (!id) throw new Error('本次会话尚未颁发令牌对，无法定位连接')
    await revokePair(id, side)
    await load()
  })

  const close = () => {
    if (action) return
    // 关闭即清空: 一次性显示的明文令牌随 state 一起丢弃
    setSecret(null); setRotated(null); setCopied(null); setError('')
  }

  const copy = async (text: string, key: string) => {
    const ok = await copyText(text)
    setCopied(ok ? key : null)
    if (!ok) setError('无法访问剪贴板，请从密码框手动复制')
  }

  /** 连接命令: 只含非敏感参数, 绝不含 web_token / assistant_token / token */
  const connectCommand = () => {
    const id = bridge.pair?.pair_id ?? secret?.pair_id
    const instance = bridge.pair?.assistant_instance_id ?? secret?.assistant_instance_id
    const session = bridge.pair?.session_id ?? secret?.session_id
    if (!id) return ''
    return [
      'python3 skills/fandecide/scripts/fandecide_inbound.py connect',
      `--url ${window.location.origin}`,
      `--pair-id ${id}`,
      `--instance-id ${instance ?? ''}`,
      `--session-id ${session ?? ''}`,
      '--version ib-1.0',
    ].join(' ')
  }

  const rejected = audit.filter((row) => row.outcome === 'rejected').slice(0, 5)
  const enabledCount = allowlist?.events.filter((event) => event.enabled).length ?? 0
  const busy = Boolean(action)
  const disabled = busy || enabled !== true

  return <section id="inbound-bridge" className="meal-settings-section">
    <div className="meal-setting-line"><h2>双向唤醒（新）</h2>
      <button type="button" className="meal-icon" title="刷新状态" aria-label="刷新双向唤醒状态"
        aria-busy={loading} disabled={loading || busy} onClick={() => { void load() }}>
        {loading ? <LoadingOutlined /> : <ReloadOutlined />}
      </button>
    </div>

    {enabled === false && <Alert type="info" showIcon message="模块未启用"
      description="双向唤醒模块的服务端开关（L0/L1）默认关闭，启用前无法颁发令牌对或发送调整。快速推荐、既有「交给 AI 调整」与 Skill 连接不受影响，仍可正常使用。" />}
    {error && enabled !== false && <Alert type="error" showIcon message={error} />}

    {allowlist && <p className="meal-muted">
      白名单版本 {allowlist.version} · 登记事件 {allowlist.events.length} 类（启用 {enabledCount} 类）
      · 永久禁止 {allowlist.forbidden.length} 项
    </p>}

    {bridge.pair ? <div className="meal-ib-pair">
      <p className="meal-muted">连接编号：{bridge.pair.pair_id}</p>
      <p>网页侧 {bridge.pair.web_state} · 助手侧 {bridge.pair.assistant_state}
        · 到期 {bridge.pair.expires_at.slice(0, 19)}</p>
    </div> : <p className="meal-muted">本次会话尚未颁发令牌对；页面刷新后内存态清空，需重新颁发才能撤销 / 轮换。</p>}

    {rejected.length > 0 && <Alert type="warning" showIcon
      message={`最近 ${rejected.length} 条拒绝记录`}
      description={rejected.map((row) => `${row.event_type}：${row.reason_code}`).join('；')} />}

    <div className="meal-actions">
      <button type="button" className="meal-button meal-primary" disabled={disabled}
        onClick={() => { void create() }}>
        {action === 'create' ? <LoadingOutlined /> : <PlusOutlined />}
        {action === 'create' ? '正在颁发' : '颁发令牌对'}
      </button>
      <button type="button" className="meal-button" disabled={disabled || !bridge.pair}
        onClick={() => { void copy(connectCommand(), 'command') }}>
        <CopyOutlined />{copied === 'command' ? '已复制' : '复制连接命令'}
      </button>
      <button type="button" className="meal-button" disabled={disabled || !bridge.pair}
        onClick={() => { void rotate('web') }}>
        {action === 'rotate:web' ? <LoadingOutlined /> : <SwapOutlined />}轮换网页侧
      </button>
      <button type="button" className="meal-button" disabled={disabled || !bridge.pair}
        onClick={() => { void rotate('assistant') }}>
        {action === 'rotate:assistant' ? <LoadingOutlined /> : <SwapOutlined />}轮换助手侧
      </button>
      <Popconfirm title="撤销网页侧令牌？" description="另一端在途回执不受影响。"
        okText="撤销" cancelText="取消" onConfirm={() => { void revoke('web') }}>
        <button type="button" className="meal-button" disabled={disabled || !bridge.pair}>
          {action === 'revoke:web' ? <LoadingOutlined /> : <DisconnectOutlined />}撤销网页侧
        </button>
      </Popconfirm>
      <Popconfirm title="撤销助手侧令牌？" description="另一端在途回执不受影响。"
        okText="撤销" cancelText="取消" onConfirm={() => { void revoke('assistant') }}>
        <button type="button" className="meal-button" disabled={disabled || !bridge.pair}>
          {action === 'revoke:assistant' ? <LoadingOutlined /> : <DisconnectOutlined />}撤销助手侧
        </button>
      </Popconfirm>
    </div>

    <div className="meal-ib-audit">
      <h3>最近审计（/audit）</h3>
      {audit.slice(0, 6).map((row) => <div className="meal-grant" key={row.event_id}>
        <div><strong>{row.event_type}</strong>
          <p>{row.outcome} · {row.reason_code} · {row.created_at?.slice(0, 19) ?? ''}</p></div>
      </div>)}
      {audit.length === 0 && <p className="meal-muted">暂无审计记录</p>}
    </div>

    <Modal title={secret ? '保存令牌对（仅显示这一次）' : '轮换后的新凭据（仅显示这一次）'}
      open={Boolean(secret || rotated)} footer={null} onCancel={close}
      closable={!busy} maskClosable={!busy} keyboard={!busy} destroyOnHidden width={560}>
      <div className="meal-form meal-connection-dialog">
        <p>凭据仅显示这一次。请立即复制并在可信终端中使用；关闭窗口后饭决不会再次显示，也不会保存明文。</p>
        {secret && <>
          <label className="meal-field meal-field-stack"><span>网页侧令牌（粘贴到「唤醒 WorkBuddy 协助修改」弹窗）</span>
            <input aria-label="网页侧令牌" type="password" value={secret.web_token} readOnly /></label>
          <label className="meal-field meal-field-stack"><span>助手侧令牌（在本机终端隐藏输入）</span>
            <input aria-label="助手侧令牌" type="password" value={secret.assistant_token} readOnly /></label>
        </>}
        {rotated && <>
          <label className="meal-field meal-field-stack">
            <span>{rotated.side === 'web' ? '网页侧' : '助手侧'}新令牌</span>
            <input aria-label="轮换后的新令牌" type="password" value={rotated.token} readOnly /></label>
          <p className="meal-muted">{rotated.message}</p>
        </>}
        <label className="meal-field meal-field-stack"><span>复制连接命令（只含非敏感参数，绝不含令牌）</span>
          <textarea aria-label="连接命令" rows={3} value={connectCommand()} readOnly /></label>
        <div className="meal-actions">
          <button type="button" className="meal-button meal-primary"
            onClick={() => { void copy(connectCommand(), 'command') }}>
            <CopyOutlined />{copied === 'command' ? '已复制' : '复制连接命令'}
          </button>
          {secret && <button type="button" className="meal-button"
            onClick={() => { void copy(secret.assistant_token, 'asst') }}>
            <CopyOutlined />{copied === 'asst' ? '已复制' : '复制助手侧令牌'}
          </button>}
          {secret && <button type="button" className="meal-button"
            onClick={() => { void copy(secret.web_token, 'web') }}>
            <CopyOutlined />{copied === 'web' ? '已复制' : '复制网页侧令牌'}
          </button>}
          <button type="button" className="meal-button" onClick={close}>完成</button>
        </div>
        <p className="meal-muted">助手侧令牌请在可信本地终端的隐藏输入中粘贴，绝不要写进命令行参数、聊天或日志。</p>
      </div>
    </Modal>
  </section>
}
