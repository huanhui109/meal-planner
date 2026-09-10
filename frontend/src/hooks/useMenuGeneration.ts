import { useCallback, useEffect, useRef, useState } from 'react'
import { generateMenu, getGenerationTask, currentWeekStart } from '../api/menu'
import type { GenerationStatus } from '../types'

const POLL_INTERVAL_MS = 2500

interface UseMenuGenerationResult {
  start: (weekStart?: string, force?: boolean) => Promise<void>
  submitting: boolean
  status: GenerationStatus | null
  running: boolean
  error: string
  reused: boolean
  reset: () => void
}

/** 提交生成任务并轮询状态, 成功或失败后回调 */
export function useMenuGeneration(onFinished?: (menuId: number) => void): UseMenuGenerationResult {
  const [submitting, setSubmitting] = useState(false)
  const [status, setStatus] = useState<GenerationStatus | null>(null)
  const [error, setError] = useState('')
  const [reused, setReused] = useState(false)
  const timer = useRef<number | null>(null)
  const finishedRef = useRef(onFinished)

  useEffect(() => {
    finishedRef.current = onFinished
  }, [onFinished])

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current)
    },
    [],
  )

  const poll = useCallback((taskId: number) => {
    timer.current = window.setTimeout(async () => {
      try {
        const task = await getGenerationTask(taskId)
        setStatus(task.status)
        if (task.status === 'succeeded' && task.menu_id) {
          setSubmitting(false)
          finishedRef.current?.(task.menu_id)
          return
        }
        if (task.status === 'failed') {
          setSubmitting(false)
          setError(task.error || '生成失败, 请重试')
          return
        }
        poll(taskId)
      } catch (err) {
        setSubmitting(false)
        setError((err as Error).message)
      }
    }, POLL_INTERVAL_MS)
  }, [])

  const start = useCallback(
    async (weekStart?: string, force = false) => {
      setSubmitting(true)
      setError('')
      setReused(false)
      setStatus('pending')
      try {
        const result = await generateMenu(weekStart || currentWeekStart(), force)
        if (result.reused && result.menu_id) {
          setReused(true)
          setStatus('succeeded')
          setSubmitting(false)
          finishedRef.current?.(result.menu_id)
          return
        }
        if (result.task_id) {
          poll(result.task_id)
          return
        }
        setSubmitting(false)
        setError('服务端未返回任务编号')
      } catch (err) {
        setSubmitting(false)
        setStatus(null)
        setError((err as Error).message)
      }
    },
    [poll],
  )

  const reset = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current)
    setSubmitting(false)
    setStatus(null)
    setError('')
    setReused(false)
  }, [])

  return {
    start,
    submitting,
    status,
    running: submitting && (status === 'pending' || status === 'running'),
    error,
    reused,
    reset,
  }
}
