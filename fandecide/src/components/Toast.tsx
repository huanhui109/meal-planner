import { useCallback, useEffect, useRef, useState } from 'react'

// 轻量 toast: 各页面共用同一套展示逻辑, 自动消失。
export function useToast(duration = 1800) {
  const [message, setMessage] = useState('')
  const timer = useRef<number | null>(null)

  const show = useCallback(
    (msg: string) => {
      setMessage(msg)
      if (timer.current) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setMessage(''), duration)
    },
    [duration],
  )

  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current) }, [])

  const node = <div className={'toast' + (message ? ' show' : '')}>{message}</div>
  return { message, show, Toast: node }
}
