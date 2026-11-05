/**
 * 双向唤醒触发弹窗 —— 与既有 MealAssistantDialog 并列, 互不修改。
 *
 * 红线:
 *  - 网页侧令牌用密码框输入, 只存 React 内存态; 内存已有则显示「已就绪」;
 *  - 逐档状态用 aria-live="polite" + inboundBridgeLabel 如实告知, 不把异常说成成功;
 *  - 结果确认区固定标注「助手只提交建议，未代替你确认」;
 *  - 只有用户显式点「选定这一餐」才调既有 actOnMeal, 关闭弹窗不自动选定;
 *  - 离线时提供 assistantTask() 纯文本「复制任务到助手」备用, 不含任何令牌。
 */
import { useEffect, useState } from 'react'
import { Alert, Modal } from 'antd'
import {
  CheckOutlined, CopyOutlined, LoadingOutlined, ReloadOutlined,
  SendOutlined, StopOutlined,
} from '@ant-design/icons'
import { assistantTask, mealSlotLabels, type MealView } from '@shared/meal'
import { inboundBridgeLabel } from '@shared/inboundBridge'
import { actOnMeal, getCurrentMeal } from '../api/meals'
import type { useInboundBridge } from '../hooks/useInboundBridge'

export default function InboundBridgeDialog({
  open, onClose, view, bridge, onCopy, onUpdated,
}: {
  open: boolean
  onClose: () => void
  view: MealView
  bridge: ReturnType<typeof useInboundBridge>
  onCopy: (text: string) => Promise<void>
  onUpdated: () => Promise<void>
}) {
  const {
    draft, setDraft, job, pending, submitting, checking, error, uncertain,
    webToken, pair, setWebToken, send, cancel, checkStatus,
  } = bridge
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState('')

  useEffect(() => { if (!open) setConfirmError('') }, [open])

  // 显式确认: 先取该餐次最新视图拿到 propose 后的最新 revision, 再走既有 accept。
  // 后端第 4 步只产出 status=proposed 的建议, 绝不自动 accept; 这里由用户点按钮完成。
  const confirm = async () => {
    setConfirming(true); setConfirmError('')
    try {
      const latest = await getCurrentMeal(view.context.meal_slot, view.context.meal_date)
      if (!latest.proposal) throw new Error('还没有可选定的方案，请稍后刷新')
      await actOnMeal(latest.proposal.id, 'accept', latest.revision)
      await onUpdated()
      onClose()
    } catch (err) {
      setConfirmError((err as Error).message)
    } finally {
      setConfirming(false)
    }
  }

  const done = job?.status === 'proposed' || job?.status === 'completed'
  const offline = job?.status === 'offline'
    || job?.status === 'disconnected' || job?.status === 'timed_out'
  const canSend = uncertain
    || (Boolean(webToken) && Boolean(pair) && !pending && Boolean(draft.trim()))
  const statusText = uncertain ? '发送状态待确认'
    : job ? inboundBridgeLabel(job.status) : '正在唤醒本机助手'

  return <Modal open={open} title="唤醒 WorkBuddy 协助修改" footer={null}
    onCancel={onClose} width={560} destroyOnHidden>
    <div className="meal-assistant-dialog">
      <div className="meal-assistant-context">
        <span>{mealSlotLabels[view.context.meal_slot]} · {view.context.servings} 人</span>
        <span>{view.proposal?.title ?? '这一餐待安排'}</span>
      </div>

      <label className="meal-assistant-label" htmlFor="ib-web-token">网页侧令牌</label>
      <input id="ib-web-token" className="meal-ib-token" type="password"
        aria-label="网页侧令牌" autoComplete="off" value={webToken}
        placeholder="在设置页「双向唤醒（新）」颁发后复制粘贴"
        onChange={(event) => setWebToken(event.target.value)} />
      <p className="meal-muted" aria-live="polite">
        {webToken ? '已就绪（仅保存在当前页面内存，刷新后需重新输入）'
          : '令牌只用于本地签名，绝不会上传、写入存储或出现在任务文本里。'}
      </p>

      <label className="meal-assistant-label" htmlFor="ib-instruction">这次想怎么吃？</label>
      <textarea id="ib-instruction" aria-label="调整要求" value={draft} maxLength={2000}
        disabled={pending} onChange={(event) => setDraft(event.target.value)} rows={4}
        placeholder="例如：今晚两个人，不想开火，清淡一点，别推荐昨天吃过的" />

      {pending && <div className="meal-assistant-progress" role="status" aria-live="polite">
        <LoadingOutlined /><span>{statusText}</span>
      </div>}
      {done && <div className="meal-assistant-progress" role="status" aria-live="polite">
        <CheckOutlined /><span>{inboundBridgeLabel(job!.status)}</span>
      </div>}
      {(error || job?.error) && <Alert type="info" showIcon message={error || job?.error} />}
      {offline && <Alert type="warning" showIcon
        message="助手离线或连接已断开；原方案未改变。可复制任务到 WorkBuddy 手动处理。" />}

      {/* 结果确认区: 固定标注 + 显式按钮, 关闭弹窗绝不自动选定 */}
      {done && <div className="meal-ib-result" role="status">
        <p className="meal-ib-disclaimer">助手只提交建议，未代替你确认</p>
        <p className="meal-muted">请由你自己决定是否选定这一餐；关闭窗口不会自动选定、不会扣库存。</p>
        {confirmError && <Alert type="error" showIcon message={confirmError} />}
        <button type="button" className="meal-button meal-primary" disabled={confirming}
          onClick={() => { void confirm() }}>
          {confirming ? <LoadingOutlined /> : <CheckOutlined />}选定这一餐
        </button>
      </div>}

      <div className="meal-actions">
        <button type="button" className="meal-button meal-primary"
          disabled={!canSend || submitting || checking}
          onClick={() => { void send() }}>
          {submitting ? <LoadingOutlined /> : <SendOutlined />}
          {uncertain ? '查询发送状态' : '唤醒助手'}
        </button>
        {pending && !submitting && <button type="button" className="meal-button"
          onClick={() => { void cancel() }}><StopOutlined />取消等待</button>}
        {!pending && <button type="button" className="meal-button"
          disabled={!draft.trim()}
          onClick={() => { void onCopy(assistantTask(view, window.location.origin, draft)) }}>
          <CopyOutlined />复制任务到助手
        </button>}
        <button type="button" className="meal-icon" aria-label="重新查询状态" title="重新查询"
          disabled={checking || submitting}
          onClick={() => { void checkStatus() }}><ReloadOutlined /></button>
      </div>
      <p className="meal-muted">双向唤醒不会自动选定、确认吃过、扣库存或发送外部消息；助手的建议需你亲自决定。</p>
    </div>
  </Modal>
}
