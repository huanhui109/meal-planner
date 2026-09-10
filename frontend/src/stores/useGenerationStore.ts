/**
 * 生成任务的全局状态
 *
 * 生成要 1-2 分钟, 用户会离开页面去别处逛 —— 所以状态不能挂在页面组件上:
 * 放在 store 里, 页面切走不中断轮询, TabBar 和头像也能显示进度点。
 * 同时天然避免了"今日页和周菜单页各起一个轮询"的重复请求。
 */
import { create } from 'zustand'
import { currentWeekStart, generateMenu, getGenerationTask } from '../api/menu'
import type { GenerationStatus } from '../types'

const POLL_INTERVAL_MS = 2500

interface GenerationState {
  submitting: boolean
  status: GenerationStatus | null
  error: string
  reused: boolean
  /** 最近一次成功的菜单 id, 供页面刷新用 */
  menuId: number | null
  listeners: Set<(menuId: number) => void>
  start: (weekStart?: string, force?: boolean) => Promise<void>
  reset: () => void
  /** 页面注册"生成成功"回调, 返回取消函数 */
  onFinished: (callback: (menuId: number) => void) => () => void
}

let timer: number | null = null

export const useGenerationStore = create<GenerationState>((set, get) => ({
  submitting: false,
  status: null,
  error: '',
  reused: false,
  menuId: null,
  listeners: new Set(),

  onFinished: (callback) => {
    get().listeners.add(callback)
    return () => get().listeners.delete(callback)
  },

  reset: () => {
    if (timer) window.clearTimeout(timer)
    timer = null
    set({ submitting: false, status: null, error: '', reused: false })
  },

  start: async (weekStart, force = false) => {
    if (timer) window.clearTimeout(timer)
    set({ submitting: true, error: '', reused: false, status: 'pending' })
    const finish = (menuId: number) => {
      set({ menuId, submitting: false, status: 'succeeded' })
      get().listeners.forEach((listener) => listener(menuId))
    }

    const poll = (taskId: number) => {
      timer = window.setTimeout(async () => {
        try {
          const task = await getGenerationTask(taskId)
          set({ status: task.status })
          if (task.status === 'succeeded' && task.menu_id) {
            finish(task.menu_id)
            return
          }
          if (task.status === 'failed') {
            set({ submitting: false, error: task.error || '生成失败, 请重试' })
            return
          }
          poll(taskId)
        } catch (error) {
          set({ submitting: false, error: (error as Error).message })
        }
      }, POLL_INTERVAL_MS)
    }

    try {
      const result = await generateMenu(weekStart || currentWeekStart(), force)
      if (result.reused && result.menu_id) {
        set({ reused: true })
        finish(result.menu_id)
        return
      }
      if (result.task_id) {
        poll(result.task_id)
        return
      }
      set({ submitting: false, error: '服务端未返回任务编号' })
    } catch (error) {
      set({ submitting: false, status: null, error: (error as Error).message })
    }
  },
}))

/** 生成中 (排队/进行中) —— TabBar 与头像的进度点看这个 */
export function useIsGenerating(): boolean {
  return useGenerationStore(
    (state) => state.submitting && (state.status === 'pending' || state.status === 'running'),
  )
}
