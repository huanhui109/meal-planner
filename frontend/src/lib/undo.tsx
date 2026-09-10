/**
 * 5 秒可撤销的 Toast
 *
 * 误触「标记已做」「换一道」是高频错误, 与其做二次确认弹窗 (打断所有人),
 * 不如做完给一个 5 秒的后悔窗口 —— 只有真的点错的人才会用到。
 */
import React from 'react'
import { message } from 'antd'

export const UNDO_SECONDS = 5

interface UndoOptions {
  key: string
  text: string
  onUndo: () => Promise<void> | void
  successText?: string
  errorText?: string
}

export function toastWithUndo({
  key,
  text,
  onUndo,
  successText = '已撤销',
  errorText = '撤销失败',
}: UndoOptions): void {
  message.open({
    key,
    type: 'success',
    duration: UNDO_SECONDS,
    content: (
      <span>
        {text}
        <a
          className="toast-undo"
          onClick={async () => {
            message.destroy(key)
            try {
              await onUndo()
              message.success(successText)
            } catch (error) {
              message.error((error as Error).message || errorText)
            }
          }}
        >
          撤销
        </a>
      </span>
    ),
  })
}
