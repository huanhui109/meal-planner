/**
 * 小程序轻组件 - 与 H5 的 components/ui 同一套视觉
 *
 * 刻意不引 NutUI/Taro UI: 参考稿的视觉定制程度很高, 覆盖成本比自写还高,
 * 而且能少 200KB+ 的包体积。
 */
import type { CSSProperties, ReactNode } from 'react'
import Taro from '@tarojs/taro'
import { Text, View } from '@tarojs/components'

type Tone = 'default' | 'accent' | 'warn' | 'danger' | 'ink'

const cx = (...parts: Array<string | false | null | undefined>) =>
  parts.filter(Boolean).join(' ')

/* ---------- 卡片 ---------- */

export function Card(props: {
  children: ReactNode
  span?: 1 | 2
  tight?: boolean
  flat?: boolean
  style?: CSSProperties
  className?: string
  onClick?: () => void
}) {
  const { children, span = 1, tight, flat, style, className, onClick } = props
  return (
    <View
      className={cx('card', tight && 'card--tight', flat && 'card--flat', onClick && 'tap', className)}
      style={style}
      onClick={onClick}
    >
      {span === 2 ? children : children}
    </View>
  )
}

/** Bento 网格: 2 列, `.bento__cell--wide` 跨两列 */
export function BentoGrid({ children }: { children: ReactNode }) {
  return <View className="bento">{children}</View>
}

export function BentoCell(props: { children: ReactNode; wide?: boolean }) {
  return (
    <View className={cx('bento__cell', props.wide && 'bento__cell--wide')}>{props.children}</View>
  )
}

/* ---------- 标题 ---------- */

export function SectionTitle(props: { text: string; hint?: string }) {
  return (
    <View className="section-title">
      <Text className="section-title__text">{props.text}</Text>
      {props.hint ? <Text className="section-title__hint">{props.hint}</Text> : null}
    </View>
  )
}

export function PageHead(props: {
  title: string
  subtitle?: string
  /** 右上角入口 (今日页的「我的」头像); 位置在胶囊按钮下方, 不会打架 */
  action?: ReactNode
}) {
  // 导航栏是自定义的 (navigationStyle: custom), 所以要自己避开状态栏
  // 与右上角的胶囊按钮; 44 是胶囊高度 + 上下留白的经验值。
  let top = 64
  try {
    // getWindowInfo 是基础库 2.20.1+ 的新 API; 老版本回退到 getSystemInfoSync
    const info = Taro.getWindowInfo
      ? Taro.getWindowInfo()
      : Taro.getSystemInfoSync()
    top = (info.statusBarHeight || 20) + 44
  } catch {
    top = 64
  }
  return (
    <View className="page-head" style={{ paddingTop: top }}>
      <View className="page-head__row">
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text className="page-title">{props.title}</Text>
          {props.subtitle ? <View className="page-sub">{props.subtitle}</View> : null}
        </View>
        {props.action}
      </View>
    </View>
  )
}

/* ---------- 按钮 ---------- */

export function PillButton(props: {
  children: ReactNode
  onClick?: () => void
  variant?: 'ink' | 'gray' | 'ghost'
  size?: 'md' | 'sm'
  block?: boolean
  disabled?: boolean
  className?: string
}) {
  const { children, onClick, variant = 'ink', size = 'md', block, disabled, className } = props
  return (
    <View
      className={cx(
        'pill',
        `pill--${variant}`,
        size === 'sm' && 'pill--sm',
        block && 'pill--block',
        disabled && 'pill--disabled',
        'tap',
        className,
      )}
      onClick={() => {
        if (!disabled) onClick?.()
      }}
    >
      {children}
    </View>
  )
}

/* ---------- 标签 ---------- */

export function Chip(props: { children: ReactNode; tone?: Tone }) {
  const tone = props.tone || 'default'
  return <Text className={cx('chip', tone !== 'default' && `chip--${tone}`)}>{props.children}</Text>
}

/* ---------- 进度条 ---------- */

export function Bar(props: { value: number; tone?: 'ink' | 'accent' | 'warn' | 'danger' }) {
  const percent = Math.max(0, Math.min(100, Math.round(props.value)))
  return (
    <View className="bar">
      <View
        className={cx('bar__fill', props.tone && props.tone !== 'ink' && `bar__fill--${props.tone}`)}
        style={{ width: `${percent}%` }}
      />
    </View>
  )
}

/* ---------- 数字磁贴 ---------- */

export function StatTile(props: {
  label: string
  value: string
  unit?: string
  hint?: string
  tone?: 'ink' | 'accent' | 'warn'
  onClick?: () => void
}) {
  const { label, value, unit, hint, tone = 'ink', onClick } = props
  return (
    <View className={cx('card', onClick && 'tap')} onClick={onClick}>
      <Text className="card__label">{label}</Text>
      <View
        className="card__value"
        style={
          tone === 'accent'
            ? { color: 'var(--color-accent-ink)' }
            : tone === 'warn'
              ? { color: 'var(--color-warn-ink)' }
              : undefined
        }
      >
        {/* 字号/字重由 .card__value 提供 ($font-number + 700), 不写内联值:
            内联 px 不经过 pxtransform, 在大屏上不会跟着缩放 */}
        <Text className="num">{value}</Text>
        {unit ? <Text className="card__unit">{unit}</Text> : null}
      </View>
      {hint ? <View className="card__hint">{hint}</View> : null}
    </View>
  )
}

/* ---------- 提示条 ---------- */

export function Banner(props: { children: ReactNode; tone?: 'default' | 'accent' | 'warn' | 'danger' }) {
  return (
    <View className={cx('banner', props.tone && props.tone !== 'default' && `banner--${props.tone}`)}>
      {props.children}
    </View>
  )
}

/* ---------- 空态 ---------- */

export function EmptyState(props: {
  title: string
  description: string
  actionLabel?: string | null
  onAction?: () => void
  loading?: boolean
}) {
  const { title, description, actionLabel, onAction, loading } = props
  return (
    <View className="empty">
      <Text className="empty__title">{title}</Text>
      <View className="empty__desc">{description}</View>
      {actionLabel ? (
        <PillButton block disabled={loading} onClick={onAction}>
          {loading ? '处理中…' : actionLabel}
        </PillButton>
      ) : null}
    </View>
  )
}

/* ---------- 骨架屏 ---------- */

export function LoadingStack({ rows = 3 }: { rows?: number }) {
  return (
    <View className="skeleton">
      {Array.from({ length: rows }).map((_, index) => (
        <View
          key={index}
          className="skeleton__line"
          style={{ width: index === rows - 1 ? '60%' : '100%' }}
        />
      ))}
    </View>
  )
}

/* ---------- 设置行 ---------- */

export function SetRow(props: {
  label: string
  value?: string
  state?: 'ok' | 'warn' | 'none'
  onClick?: () => void
}) {
  const { label, value, state = 'none', onClick } = props
  return (
    <View className={cx('set-row', onClick && 'tap')} onClick={onClick}>
      <View style={{ display: 'flex', alignItems: 'center' }}>
        {state !== 'none' ? <View className={cx('state-dot', `state-dot--${state}`)} /> : null}
        <Text className="set-row__label">{label}</Text>
      </View>
      <Text className="set-row__value">{value || '未设置'}</Text>
    </View>
  )
}

export function SetGroup(props: { title?: string; children: ReactNode }) {
  return (
    <View className="set-group">
      {props.title ? <View className="set-group__title">{props.title}</View> : null}
      {props.children}
    </View>
  )
}

/* ---------- 下一步指引卡 ---------- */

export function NextStepCard(props: {
  title: string
  description: string
  actionLabel?: string | null
  onAction?: () => void
  loading?: boolean
}) {
  const { title, description, actionLabel, onAction, loading } = props
  return (
    <View className="next-step">
      <Text className="next-step__title">{title}</Text>
      <View className="next-step__desc">{description}</View>
      {actionLabel ? (
        <PillButton block disabled={loading} onClick={onAction} className="next-step__cta">
          {loading ? '处理中…' : actionLabel}
        </PillButton>
      ) : null}
    </View>
  )
}

export { cx }
