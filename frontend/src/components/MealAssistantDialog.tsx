import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Modal } from 'antd'
import {
  ArrowRightOutlined, CheckOutlined, CopyOutlined, LoadingOutlined,
  ReloadOutlined, SendOutlined, StopOutlined,
} from '@ant-design/icons'
import type { MealView } from '@shared/meal'
import { adjustmentLabel, assistantTask, mealSlotLabels } from '@shared/meal'
import type { useMealAssistant } from '../hooks/useMealAssistant'

export default function MealAssistantDialog({ open, onClose, view, assistant, onCopy }: {
  open: boolean
  onClose: () => void
  view: MealView
  assistant: ReturnType<typeof useMealAssistant>
  onCopy: (text: string) => Promise<void>
}) {
  const {
    draft, setDraft, status, modelStatus, checking, checkStatus, checkModelStatus,
    job, pending, submitting, error, uncertain, restoring,
  } = assistant
  useEffect(() => {
    if (open) { void checkStatus(); void checkModelStatus() }
  }, [open, checkStatus, checkModelStatus])
  const canSend = uncertain || ((modelStatus?.available === true || status?.state === 'online')
    && !pending && !restoring && Boolean(draft.trim()))

  return <Modal open={open} title="交给 AI 调整" footer={null} onCancel={onClose} width={560}>
    <div className="meal-assistant-dialog">
      <div className="meal-assistant-context">
        <span>{mealSlotLabels[view.context.meal_slot]} · {view.context.servings} 人</span>
        <span>{view.proposal?.title ?? '这一餐待安排'}</span>
      </div>
      <label className="meal-assistant-label" htmlFor="meal-ai-instruction">这次想怎么吃？</label>
      <textarea id="meal-ai-instruction" aria-label="调整要求" value={draft} maxLength={2000}
        disabled={pending} onChange={(event) => setDraft(event.target.value)} rows={4}
        placeholder="例如：今晚两个人，不想开火，清淡一点，别推荐昨天吃过的" />
      <div className="meal-assistant-connection">
        <span>{checking ? <><LoadingOutlined />正在检查助手连接</>
          : modelStatus?.available ? modelStatus.message
            : status?.message ?? '暂时无法确认助手状态'}</span>
        <button type="button" className="meal-icon" aria-label="重新检查助手状态" title="重新检查"
          disabled={checking || submitting} onClick={() => { void checkStatus(); void checkModelStatus() }}>
          <ReloadOutlined /></button>
      </div>
      {pending && <div className="meal-assistant-progress" role="status" aria-live="polite">
        <LoadingOutlined /><span>{uncertain ? '发送状态待确认' : adjustmentLabel(job)}</span>
      </div>}
      {job?.status === 'completed' && <div className="meal-assistant-progress" role="status">
        <CheckOutlined /><span>新方案已保存，等你决定</span>
      </div>}
      {(error || job?.error) && <Alert type={job?.status === 'failed' ? 'warning' : 'info'} showIcon
        message={error || job?.error} />}
      <div className="meal-actions">
        <button type="button" className="meal-button meal-primary" disabled={!canSend || submitting || checking}
          onClick={() => { void assistant.send() }}>
          {submitting ? <LoadingOutlined /> : <SendOutlined />}{uncertain ? '查询发送状态' : '发送给助手'}
        </button>
        {pending && !submitting && <button type="button" className="meal-button"
          onClick={() => { void assistant.cancel() }}><StopOutlined />取消等待</button>}
        {!pending && <button type="button" className="meal-button" disabled={!draft.trim()}
          onClick={() => { void onCopy(assistantTask(view, window.location.origin, draft)) }}>
          <CopyOutlined />复制调整任务
        </button>}
      </div>
      {!pending && <Link to="/me#assistant" className="meal-text-link" onClick={onClose}>
        助手连接<ArrowRightOutlined />
      </Link>}
    </div>
  </Modal>
}
