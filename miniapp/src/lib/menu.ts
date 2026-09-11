/**
 * 生成任务的等待与轮询
 *
 * 后端生成是异步的 (202 + task_id), 小程序没有 SSE 也没必要上 WebSocket,
 * 直接轮询就行: 3 秒一次, 最多等 5 分钟, 中途用户切走页面也不会卡住。
 */
import type {
  GenerateAccepted,
  GenerationMode,
  GenerationTask,
  MealDetail,
  MenuDetail,
} from '@shared/types'

import { getGenerationTask, generateMenu } from './api'

const POLL_INTERVAL = 3000
const POLL_TIMEOUT = 5 * 60 * 1000

export const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** 提交生成, 已经存在草稿时后端会直接复用 (reused=true) */
export async function startGeneration(
  weekStart: string,
  force = false,
  mode: GenerationMode = 'auto',
): Promise<GenerateAccepted> {
  return generateMenu(weekStart, force, mode)
}

/** 轮询到出结果为止; onProgress 每次拿到新状态都会回调 */
export async function waitForGeneration(
  taskId: number,
  onProgress?: (task: GenerationTask) => void,
): Promise<GenerationTask> {
  const deadline = Date.now() + POLL_TIMEOUT
  let last: GenerationTask | null = null
  while (Date.now() < deadline) {
    const task = await getGenerationTask(taskId)
    last = task
    onProgress?.(task)
    if (task.status === 'succeeded' || task.status === 'failed') return task
    await sleep(POLL_INTERVAL)
  }
  return (
    last || {
      task_id: taskId,
      status: 'failed',
      menu_id: null,
      week_start_date: '',
      error: '生成超时, 请稍后重试',
      created_at: null,
      finished_at: null,
    }
  )
}

/** 从菜单里取某天的某一餐 */
export function findMeal(menu: MenuDetail | null, date: string, mealId: number): MealDetail | null {
  if (!menu) return null
  for (const day of menu.days) {
    if (day.date !== date) continue
    const meal = day.meals.find((item) => item.id === mealId)
    if (meal) return meal
  }
  return null
}

/** 今天还没做的餐 */
export function todaysMeals(menu: MenuDetail | null, today: string): MealDetail[] {
  if (!menu) return []
  return menu.days.find((day) => day.date === today)?.meals ?? []
}
