/**
 * 生成任务的页面级用法
 *
 * 真正的状态在 useGenerationStore (全局), 这里只是把 store 包成页面习惯的
 * 形状, 并注册"生成成功"回调。页面切走轮询不会停, 回来还能接着看进度。
 */
import { useEffect } from 'react'
import { useGenerationStore } from '../stores/useGenerationStore'
import type { GenerationStatus } from '../types'

interface UseMenuGenerationResult {
  start: (weekStart?: string, force?: boolean) => Promise<void>
  submitting: boolean
  status: GenerationStatus | null
  running: boolean
  error: string
  reused: boolean
  reset: () => void
}

export function useMenuGeneration(onFinished?: (menuId: number) => void): UseMenuGenerationResult {
  const submitting = useGenerationStore((state) => state.submitting)
  const status = useGenerationStore((state) => state.status)
  const error = useGenerationStore((state) => state.error)
  const reused = useGenerationStore((state) => state.reused)
  const start = useGenerationStore((state) => state.start)
  const reset = useGenerationStore((state) => state.reset)
  const onFinishedChange = useGenerationStore((state) => state.onFinished)

  useEffect(() => {
    if (!onFinished) return undefined
    return onFinishedChange(onFinished)
  }, [onFinished, onFinishedChange])

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
