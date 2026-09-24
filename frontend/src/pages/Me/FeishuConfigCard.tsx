/**
 * 飞书机器人配置卡 (我的 → 自动化)
 *
 * 为什么让用户自己填: 飞书应用凭证决定"消息以谁的身份发出去"。一个家庭里每个人
 * 的飞书租户不同, 部署方配一份根本覆盖不到所有人 —— 所以每人配自己的一份,
 * 谁配谁用, 互相看不到。没配也能正常用全部功能, 只是收不到飞书推送。
 *
 * App Secret 是只写字段: 后端只回掩码, 留空提交表示沿用原值。
 */
import React, { useCallback, useEffect, useState } from 'react'
import { message } from 'antd'
import {
  deleteFeishuConfig,
  getFeishuConfig,
  saveFeishuConfig,
  testFeishuConfig,
} from '../../api/automation'
import { Banner, Card, Chip, LoadingStack, PillButton } from '../../components/ui'
import { Field, TextInput } from '../../components/ui/form'
import type { FeishuConfigView } from '../../types'

/** 接收方 ID 类型 - 三选一, 各自给一句"怎么拿到" */
const RECEIVE_TYPES = [
  {
    value: 'open_id',
    label: '我的 open_id',
    hint: '最稳。在飞书开放平台「API 调试台」用手机号/邮箱查自己在这个应用下的 open_id, 形如 ou_xxx。',
  },
  {
    value: 'email',
    label: '飞书邮箱',
    hint: '最省事。填你登录飞书用的邮箱即可, 不需要先查 open_id。',
  },
  {
    value: 'chat_id',
    label: '群 chat_id',
    hint: '想推到家庭群时用。把应用机器人拉进群, 群设置里的 chat_id 形如 oc_xxx。',
  },
] as const

interface Props {
  /** 状态卡里显示"最近推送"; 配置变动后通知父组件刷新 */
  onChanged?: () => void
}

const FeishuConfigCard: React.FC<Props> = ({ onChanged }) => {
  const [view, setView] = useState<FeishuConfigView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [appId, setAppId] = useState('')
  const [appSecret, setAppSecret] = useState('')
  const [receiveId, setReceiveId] = useState('')
  const [receiveType, setReceiveType] = useState('open_id')
  const [remark, setRemark] = useState('')
  const [enabled, setEnabled] = useState(true)

  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [showGuide, setShowGuide] = useState(false)

  const applyView = useCallback((next: FeishuConfigView) => {
    setView(next)
    setAppId(next.app_id)
    setReceiveId(next.receive_id)
    setReceiveType(next.receive_id_type || 'open_id')
    setRemark(next.remark)
    setEnabled(next.enabled)
    setAppSecret('')
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      applyView(await getFeishuConfig())
      setError('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [applyView])

  useEffect(() => {
    load()
  }, [load])

  const handleSave = async () => {
    setSaving(true)
    try {
      const next = await saveFeishuConfig({
        app_id: appId.trim(),
        // 留空 = 不改已保存的密钥
        app_secret: appSecret.trim() ? appSecret.trim() : null,
        receive_id: receiveId.trim(),
        receive_id_type: receiveType,
        remark: remark.trim(),
        enabled,
      })
      applyView(next)
      message.success('已保存')
      onChanged?.()
    } catch (err) {
      message.error((err as Error).message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      const result = await testFeishuConfig()
      if (result.ok) {
        message.success(result.message)
      } else {
        message.error(result.message)
      }
      await load()
      onChanged?.()
    } catch (err) {
      message.error((err as Error).message || '测试失败')
    } finally {
      setTesting(false)
    }
  }

  const handleClear = async () => {
    try {
      await deleteFeishuConfig()
      await load()
      message.success('已清除, 将回落到部署默认配置')
      onChanged?.()
    } catch (err) {
      message.error((err as Error).message || '清除失败')
    }
  }

  if (loading) return <LoadingStack rows={3} />
  if (error) {
    return (
      <Card tight>
        <Banner tone="warn" title="读不到飞书配置" text={error} />
        <PillButton variant="gray" block onClick={load}>
          重试
        </PillButton>
      </Card>
    )
  }

  const missing = view?.missing_fields ?? []
  const usingOwnConfig = view?.source === 'user'
  const typeHint = RECEIVE_TYPES.find((t) => t.value === receiveType)?.hint ?? ''

  return (
    <Card tight>
      <div className="card-head">
        <div>
          <div className="card-title">飞书机器人</div>
          <div className="card-sub">
            {view?.configured
              ? usingOwnConfig
                ? '已用你自己填的应用发消息'
                : '目前用部署默认配置发消息, 填下面的可以改成你自己的'
              : '还没配好, 配完就能把每日菜单推到飞书'}
          </div>
        </div>
        <Chip tone={view?.configured ? 'green' : 'gray'}>
          {view?.configured ? (enabled ? '已配置' : '已停用') : '未配置'}
        </Chip>
      </div>

      {missing.length > 0 && (
        <Banner
          tone="warn"
          title={`还差 ${missing.length} 项`}
          text={`缺 ${missing.join(' / ')} · 三项都填好才能发出消息`}
        />
      )}

      {view?.last_error && (
        <Banner tone="warn" title="最近一次失败" text={view.last_error} />
      )}

      {/* ---------- 参数说明指引 ---------- */}
      <button
        type="button"
        className="guide-toggle"
        onClick={() => setShowGuide((prev) => !prev)}
      >
        {showGuide ? '收起配置说明' : '这些参数去哪儿拿? (3 步)'}
      </button>

      {showGuide && (
        <div className="guide">
          <ol className="guide-steps">
            <li>
              <b>建应用</b>：打开飞书开放平台 → 开发者后台 → 创建「企业自建应用」(个人飞书账号也能建)。名字随便填, 例如「饭决」。
            </li>
            <li>
              <b>抄两个值</b>：进入应用 →「凭证与基础信息」, 复制 <code>App ID</code> 和{' '}
              <code>App Secret</code>。
            </li>
            <li>
              <b>开权限并发布</b>：在「权限管理」里勾上
              <code>im:message</code>(发送消息) 与 <code>im:message:send_as_bot</code>,
              然后「版本管理与发布」创建版本并发布。没发布的话接口会报权限错误。
            </li>
            <li>
              <b>填接收人</b>：直接填你的飞书邮箱最省事; 想推到群里就填群 chat_id。
            </li>
          </ol>
          <div className="guide-note">
            机器人只能给「应用可用范围内」的人发消息。若提示收不到, 检查应用「可用范围」里有没有包含你自己。
          </div>
          <div className="guide-note">
            在「我的 → 自动化」没配时, 登录仍可用账号/手机号方式, 只是收不到飞书提醒。
          </div>
        </div>
      )}

      {/* ---------- 表单 ---------- */}
      <Field
        label="App ID"
        hint="飞书应用「凭证与基础信息」里的 App ID, 形如 cli_xxx"
      >
        <TextInput value={appId} onChange={setAppId} placeholder="cli_xxxxxxxxxxxx" />
      </Field>

      <Field
        label="App Secret"
        hint={
          view?.has_secret
            ? `已保存 ${view.app_secret_masked}, 留空表示不改动`
            : '飞书应用「凭证与基础信息」里的 App Secret, 保存后只显示掩码'
        }
      >
        <input
          className="text-input"
          type="password"
          value={appSecret}
          placeholder={view?.has_secret ? '留空则沿用已保存的密钥' : '粘贴 App Secret'}
          onChange={(event) => setAppSecret(event.target.value)}
        />
      </Field>

      <Field label="接收方类型" hint={typeHint}>
        <div className="chip-row is-fill">
          {RECEIVE_TYPES.map((type) => (
            <button
              key={type.value}
              type="button"
              className={`chip-option ${receiveType === type.value ? 'is-on' : ''}`}
              onClick={() => setReceiveType(type.value)}
            >
              {type.label}
            </button>
          ))}
        </div>
      </Field>

      <Field
        label="接收方 ID"
        hint={
          receiveType === 'email'
            ? '填你的飞书登录邮箱, 例如 you@company.com'
            : receiveType === 'chat_id'
              ? '群 chat_id 形如 oc_xxx'
              : '你的 open_id 形如 ou_xxx'
        }
      >
        <TextInput value={receiveId} onChange={setReceiveId} placeholder="接收消息的人或群" />
      </Field>

      <Field label="备注" hint="只是给自己看的, 例如「家庭群」">
        <TextInput value={remark} onChange={setRemark} placeholder="可留空" />
      </Field>

      <button
        type="button"
        className={`switch-row ${enabled ? 'is-on' : ''}`}
        onClick={() => setEnabled((prev) => !prev)}
      >
        <span>{enabled ? '已启用推送' : '已停用推送'}</span>
        <i className="state-dot" />
      </button>

      <div className="stack-actions">
        <PillButton block loading={saving} onClick={handleSave}>
          保存飞书配置
        </PillButton>
        <PillButton variant="gray" block loading={testing} onClick={handleTest}>
          发送测试消息
        </PillButton>
        {usingOwnConfig && (
          <PillButton variant="gray" block onClick={handleClear}>
            清除个人配置
          </PillButton>
        )}
      </div>
    </Card>
  )
}

export default FeishuConfigCard
