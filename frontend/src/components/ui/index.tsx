/**
 * H5 UI 组件层 - 设计系统的落地实现
 *
 * 页面只用这里的组件与 global.css 里的类名, 不再直接写 antd 的卡片/按钮,
 * 这样换肤只需要改 tokens 与这一层。
 */
import React from 'react'
import { Empty, Skeleton, Spin } from 'antd'
import type { NextStep } from '@shared/next-step'
import { formatMonthDay, WEEKDAY_SHORT_SAFE } from './day-strip-helper'

export { LogoLockup, LogoMark } from './logo'

type Tone = 'ink' | 'gray' | 'ghost' | 'green' | 'warn' | 'danger'

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 窄屏占几列 (Bento 网格共 2 列) */
  span?: 1 | 2
  /** 宽屏 (>=1024px) 占几列 (网格共 6 列) */
  lg?: 2 | 3 | 4 | 6
  /** 更紧凑的内边距 */
  tight?: boolean
}

export const Card: React.FC<CardProps> = ({
  span = 1,
  lg,
  tight,
  className = '',
  children,
  ...rest
}) => (
  <div
    className={`card ${tight ? 'tight' : ''} ${span === 2 ? 'span-2' : ''} ${
      lg ? `lg-${lg}` : ''
    } ${className}`.trim()}
    {...rest}
  >
    {children}
  </div>
)

export const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="section-title">{children}</div>
)

interface PillButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'ink' | 'gray' | 'ghost'
  size?: 'md' | 'sm'
  block?: boolean
  loading?: boolean
}

export const PillButton: React.FC<PillButtonProps> = ({
  variant = 'ink',
  size = 'md',
  block,
  loading,
  className = '',
  children,
  disabled,
  ...rest
}) => (
  <button
    type="button"
    className={`pill pill--${variant} ${size === 'sm' ? 'pill--sm' : ''} ${
      block ? 'pill--block' : ''
    } ${className}`.trim()}
    disabled={disabled || loading}
    {...rest}
  >
    {loading ? <Spin size="small" /> : children}
  </button>
)

export const Chip: React.FC<{ tone?: Tone; children: React.ReactNode }> = ({
  tone = 'gray',
  children,
}) => <span className={`chip chip--${tone}`}>{children}</span>

export const Bar: React.FC<{ percent: number; tone?: 'ink' | 'ok' | 'over' }> = ({
  percent,
  tone = 'ink',
}) => (
  <div className={`bar ${tone === 'ink' ? '' : `is-${tone}`}`}>
    <i style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
  </div>
)

interface StatTileProps {
  label: string
  value: React.ReactNode
  unit?: string
  hint?: React.ReactNode
  hintTone?: 'muted' | 'danger' | 'accent' | 'warn'
  span?: 1 | 2
  lg?: 2 | 3 | 4 | 6
  children?: React.ReactNode
}

export const StatTile: React.FC<StatTileProps> = ({
  label,
  value,
  unit,
  hint,
  hintTone = 'muted',
  span = 1,
  lg,
  children,
}) => (
  <Card span={span} lg={lg} className="stat-tile">
    <div className="stat-label">{label}</div>
    <div className="stat-value">
      {value}
      {unit && <span className="stat-unit">{unit}</span>}
    </div>
    {children}
    {hint && (
      <div className={`stat-hint ${hintTone === 'muted' ? '' : `is-${hintTone}`}`}>{hint}</div>
    )}
  </Card>
)

interface BannerProps {
  tone?: 'warn' | 'accent' | 'info'
  icon?: React.ReactNode
  title: React.ReactNode
  text?: React.ReactNode
}

export const Banner: React.FC<BannerProps> = ({ tone = 'warn', icon, title, text }) => (
  <div className={`banner ${tone === 'warn' ? '' : `is-${tone}`}`}>
    {icon && <div className="banner-icon">{icon}</div>}
    <div className="banner-text">
      <b>{title}</b>
      {text && <span>{text}</span>}
    </div>
  </div>
)

export const EmptyState: React.FC<{
  title: string
  description?: string
  actionLabel?: string
  onAction?: () => void
  loading?: boolean
  icon?: React.ReactNode
}> = ({ title, description, actionLabel, onAction, loading, icon }) => (
  <div style={{ textAlign: 'center', padding: '12px 0' }}>
    <Empty image={icon ?? Empty.PRESENTED_IMAGE_SIMPLE} description={null} />
    <div className="empty-hint" style={{ marginTop: 12, fontWeight: 600, color: 'var(--color-ink)' }}>
      {title}
    </div>
    {description && <div className="empty-hint">{description}</div>}
    {actionLabel && onAction && (
      <PillButton onClick={onAction} loading={loading}>
        {actionLabel}
      </PillButton>
    )}
  </div>
)

interface PageHeadProps {
  title: string
  subtitle?: React.ReactNode
  extra?: React.ReactNode
}

/** 页头: 标题 + 一句"现在是什么状态、下一步做什么" */
export const PageHead: React.FC<PageHeadProps> = ({ title, subtitle, extra }) => (
  <div className="page-head">
    <div>
      <h1 className="page-title">{title}</h1>
      {subtitle && <div className="page-sub">{subtitle}</div>}
    </div>
    {extra && <div className="page-head-extra">{extra}</div>}
  </div>
)

export const LoadingStack: React.FC<{ rows?: number }> = ({ rows = 5 }) => (
  <div className="skeleton-stack">
    <div className="card">
      <Skeleton active paragraph={{ rows }} />
    </div>
  </div>
)

interface DayStripProps {
  days: Array<{ date: string; weekday: number; isToday?: boolean }>
  selected: string
  onSelect: (date: string) => void
}

/** 星期条: 选中态是黑底白字, 今天多一个绿点 */
export const DayStrip: React.FC<DayStripProps> = ({ days, selected, onSelect }) => (
  <div className="day-strip">
    {days.map((day) => (
      <button
        key={day.date}
        type="button"
        className={`day-pill ${selected === day.date ? 'is-selected' : ''} ${
          day.isToday ? 'is-today' : ''
        }`}
        onClick={() => onSelect(day.date)}
      >
        <small>{WEEKDAY_SHORT_SAFE[day.weekday] ?? ''}</small>
        <b>{formatMonthDay(day.date).replace('月', '/').replace('日', '')}</b>
      </button>
    ))}
  </div>
)

/** 首页置顶的"下一步"卡: 黑底, 一句话 + 一个动作 */
export const NextStepCard: React.FC<{
  step: NextStep
  onAction: (step: NextStep) => void
  loading?: boolean
}> = ({ step, onAction, loading }) => (
  <div className="next-step span-2 lg-3">
    <div className="next-step-label">下一步</div>
    <div className="next-step-title">{step.title}</div>
    <div className="next-step-desc">{step.description}</div>
    {step.actionLabel && (
      <div className="next-step-actions">
        <button
          type="button"
          className="pill pill--gray"
          onClick={() => onAction(step)}
          disabled={loading}
        >
          {step.actionLabel}
        </button>
      </div>
    )}
  </div>
)
