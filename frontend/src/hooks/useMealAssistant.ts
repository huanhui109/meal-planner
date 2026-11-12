import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AssistantAdjustment, AssistantAdjustmentRequest, MealView, ModelConnectionStatus, WorkBuddyStatus,
} from '@shared/meal'
import { adjustmentPending } from '@shared/meal'
import {
  cancelAssistantAdjustment, getAssistantAdjustment, getCurrentAdjustment,
  getModelStatus, getWorkBuddyStatus, startAssistantAdjustment,
} from '../api/meals'

export function useMealAssistant(view: MealView | null, onUpdated: () => Promise<void>) {
  const [job, setJob] = useState<AssistantAdjustment | null>(null)
  const [draft, setDraft] = useState('')
  const [status, setStatus] = useState<WorkBuddyStatus | null>(null)
  const [modelStatus, setModelStatus] = useState<ModelConnectionStatus | null>(null)
  const [checking, setChecking] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [uncertain, setUncertain] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const epoch = useRef(0)
  const lock = useRef(false)
  const statusRequest = useRef(0)
  const modelStatusRequest = useRef(0)
  const request = useRef<AssistantAdjustmentRequest | null>(null)
  const applied = useRef('')
  const date = view?.context.meal_date
  const slot = view?.context.meal_slot

  useEffect(() => {
    const ticket = ++epoch.current
    setJob(null); setDraft(''); setError(''); setUncertain(false); setSubmitting(false)
    request.current = null
    lock.current = false
    if (!date || !slot) return
    setRestoring(true)
    void getCurrentAdjustment(date, slot).then((next) => {
      if (ticket !== epoch.current) return
      setJob(next)
      if (next) setDraft(next.instruction)
    }).catch(() => {
      if (ticket === epoch.current) setError('暂时无法查询上次调整，请刷新后再发送')
    }).finally(() => {
      if (ticket === epoch.current) setRestoring(false)
    })
    return () => { epoch.current += 1 }
  }, [date, slot])

  // 模型状态用独立 ticket，避免较慢的 /assistant/model 请求覆盖 WorkBuddy 状态或彼此错乱。
  const checkModelStatus = useCallback(async () => {
    const ticket = ++modelStatusRequest.current
    try {
      const next = await getModelStatus()
      if (ticket === modelStatusRequest.current) setModelStatus(next)
    } catch {
      if (ticket === modelStatusRequest.current) setModelStatus(null)
    }
  }, [])

  const checkStatus = useCallback(async () => {
    const ticket = ++statusRequest.current
    setChecking(true)
    void checkModelStatus()
    try {
      const next = await getWorkBuddyStatus()
      if (ticket === statusRequest.current) setStatus(next)
    } catch (err) {
      if (ticket === statusRequest.current) {
        setStatus(null)
        setError((err as Error).message)
      }
    } finally {
      if (ticket === statusRequest.current) setChecking(false)
    }
  }, [checkModelStatus])

  useEffect(() => {
    if (!job || !adjustmentPending(job)) return
    const ticket = epoch.current
    const timer = window.setTimeout(() => {
      void getAssistantAdjustment(job.id).then((next) => {
        if (ticket === epoch.current) { setJob(next); setError('') }
      }).catch((err: Error) => {
        if (ticket === epoch.current) {
          setError(err.message)
          setJob({ ...job, poll_after_ms: 6000 })
        }
      })
    }, Math.max(1000, job.poll_after_ms))
    return () => window.clearTimeout(timer)
  }, [job])

  useEffect(() => {
    if (job?.status !== 'completed' || applied.current === job.id) return
    applied.current = job.id
    void onUpdated()
  }, [job, onUpdated])

  const send = async () => {
    if (lock.current || !view || !draft.trim() || restoring || adjustmentPending(job)) return
    lock.current = true
    const ticket = ++epoch.current
    setSubmitting(true); setError('')
    const payload = request.current ?? {
      request_id: crypto.randomUUID(), instruction: draft.trim(),
      context: view.context, expected_revision: view.revision,
    }
    request.current = payload
    try {
      const next = uncertain
        ? await getAssistantAdjustment(payload.request_id)
        : await startAssistantAdjustment(payload)
      if (ticket === epoch.current) {
        setJob(next); setUncertain(false); request.current = null
      }
    } catch (err) {
      if (ticket !== epoch.current) return
      const httpStatus = (err as { status?: number }).status
      if (httpStatus && httpStatus < 500) {
        setError((err as Error).message)
        setUncertain(false); request.current = null
        if (httpStatus === 409) void onUpdated()
      } else {
        setUncertain(true)
        setError('发送状态尚未确认，请查询状态。不会自动重复发送，你的输入已保留。')
      }
    } finally {
      if (ticket === epoch.current) { setSubmitting(false); lock.current = false }
    }
  }

  const cancel = async () => {
    const id = uncertain ? request.current?.request_id : job?.id
    if (lock.current || !id) return
    lock.current = true
    const ticket = ++epoch.current
    setSubmitting(true)
    try {
      const next = await cancelAssistantAdjustment(id)
      if (ticket === epoch.current) {
        setJob(next); setUncertain(false); setError(''); request.current = null
      }
    } catch (err) {
      if (ticket === epoch.current) {
        setError((err as Error).message)
        if (job) setJob({ ...job })
      }
    } finally {
      if (ticket === epoch.current) { lock.current = false; setSubmitting(false) }
    }
  }

  return {
    job, draft, setDraft, status, modelStatus, checking, checkStatus, checkModelStatus,
    submitting, error, uncertain, restoring,
    pending: submitting || uncertain || adjustmentPending(job),
    send, cancel,
  }
}
