/**
 * 「我的」抽屉
 *
 * 参考稿里「我的」不再是 Tab —— 它挂在右上角头像上:
 *   * 宽屏 (>=1024px) 从右侧滑出
 *   * 窄屏 (<1024px) 从底部升起, 和手机上的原生手感一致
 * 交互组件继续用 antd Drawer (有焦点管理 / ESC / 遮罩), 只换外观。
 */
import React, { useEffect, useState } from 'react'
import { Drawer } from 'antd'

function useIsDesktop(): boolean {
  const [desktop, setDesktop] = useState(
    () => typeof window !== 'undefined' && window.innerWidth >= 1024,
  )
  useEffect(() => {
    const query = window.matchMedia('(min-width: 1024px)')
    const onChange = (event: MediaQueryListEvent) => setDesktop(event.matches)
    setDesktop(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return desktop
}

interface MeSheetProps {
  open: boolean
  onClose: () => void
  children: React.ReactNode
}

const MeSheet: React.FC<MeSheetProps> = ({ open, onClose, children }) => {
  const desktop = useIsDesktop()
  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement={desktop ? 'right' : 'bottom'}
      width={desktop ? 420 : undefined}
      height={desktop ? undefined : '88dvh'}
      closable={false}
      rootClassName="me-sheet demo"
      styles={{
        body: { padding: 0 },
        content: desktop
          ? { borderRadius: '28px 0 0 28px' }
          : { borderRadius: '28px 28px 0 0' },
      }}
      maskClosable
      destroyOnHidden
    >
      {children}
    </Drawer>
  )
}

export default MeSheet
