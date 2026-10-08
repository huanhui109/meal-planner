/**
 * 「我的」- 偏好四组 + 机器人状态
 *
 * 结构照参考稿: 一行一个分组, 右侧是"当前值 + 状态点", 点进去才是表单。
 * 这样抽屉里一眼能看出"哪几项还没填", 不用翻五个表单找。
 */
import React, { useCallback, useEffect, useState } from 'react'
import { message } from 'antd'
import {
  BellOutlined,
  FireOutlined,
  HomeOutlined,
  LogoutOutlined,
  SafetyOutlined,
  ShoppingOutlined,
  WalletOutlined,
} from '@ant-design/icons'
import { Banner, Card, Chip, LoadingStack, PillButton } from '../../components/ui'
import { getAutomationStatus } from '../../api/automation'
import { currentWeekStart, rebuildMenuFromFridge } from '../../api/menu'
import { getToday } from '../../api/today'
import FeishuConfigCard from './FeishuConfigCard'
import { logout } from '../../api/auth'
import { usePreferenceStore } from '../../stores/usePreferenceStore'
import { useThemeStore } from '../../stores/useThemeStore'
import { brand } from '@shared/brand'
import { formatMoney } from '@shared/format'
import { timelineTone, type ThemeName } from '@shared/index'
import type {
  AutomationStatus,
  CurrentUser,
  FridgeRebuildSummary,
  TimelineEntry,
} from '../../types'

interface MePanelProps {
  user: CurrentUser
  onNavigate: (to: string) => void
}

/** 「我的」面板里的一行: 多数是跳转表单, 「按冰箱重排」这种是当场执行动作 */
interface GroupRow {
  key: string
  icon: React.ReactNode
  title: string
  value: string
  hint: string
  done: boolean
  to: string
  action?: () => void
}

const MePanel: React.FC<MePanelProps> = ({ user, onNavigate }) => {
  const { summary, loaded, loading, fetchSummary } = usePreferenceStore()
  const [automation, setAutomation] = useState<AutomationStatus | null>(null)
  const [automationError, setAutomationError] = useState('')
  const [showAutomation, setShowAutomation] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [fridgeSummary, setFridgeSummary] = useState<FridgeRebuildSummary | null>(null)

  const refreshAutomation = useCallback(() => {
    getAutomationStatus()
      .then((next) => {
        setAutomation(next)
        setAutomationError('')
      })
      .catch((error: Error) => setAutomationError(error.message))
  }, [])

  useEffect(() => {
    fetchSummary().catch((error: Error) => message.error(error.message))
    refreshAutomation()
  }, [fetchSummary, refreshAutomation])

  /** 按冰箱重排本周: 同步返回, 排完告诉用户清空了多少、还得买多少 */
  const handleFridgeRebuild = useCallback(async () => {
    setRebuilding(true)
    try {
      const payload = await rebuildMenuFromFridge(currentWeekStart())
      setFridgeSummary(payload.summary)
      message.success(
        `已重排 ${payload.summary.changed_items} 餐, 其中 ${payload.summary.cookable_now} 餐现在就能做`,
      )
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setRebuilding(false)
    }
  }, [])

  const handleLogout = useCallback(async () => {
    try {
      await logout()
    } finally {
      window.location.assign('/login')
    }
  }, [])

  if (!loaded && loading) {
    return (
      <div className="me-panel">
        <LoadingStack rows={5} />
      </div>
    )
  }

  const household = summary?.household ?? null
  const diet = summary?.diet_preference ?? null
  const allergy = summary?.allergy_restriction ?? null
  const goal = summary?.health_goal ?? null
  const budget = summary?.budget ?? null

  const groups: GroupRow[] = [
    {
      key: 'household',
      icon: <HomeOutlined />,
      title: '家庭与厨房',
      value: household
        ? `${household.member_count} 人 · 每日 ${household.meals_per_day} 餐`
        : '未填写',
      hint: household ? (household.kitchen_equipments ?? []).slice(0, 3).join(' · ') : '决定每餐做几人份',
      done: Boolean(household),
      to: '/preferences?focus=household',
    },
    {
      key: 'taste',
      icon: <FireOutlined />,
      title: '口味与安全',
      value: diet || allergy ? `${(diet?.cuisines ?? []).slice(0, 2).join(' · ') || '不限菜系'}` : '未填写',
      hint:
        allergy && (allergy.allergens ?? []).length + (allergy.avoid_ingredients ?? []).length > 0
          ? `已避 ${(allergy.allergens ?? []).length + (allergy.avoid_ingredients ?? []).length} 项过敏/忌口`
          : '不填忌口会按常规配餐',
      done: Boolean(diet) && Boolean(allergy),
      to: '/preferences?focus=taste',
    },
    {
      key: 'goal',
      icon: <WalletOutlined />,
      title: '目标与预算',
      value: budget ? `每日 ${formatMoney(budget.weekday_daily_budget)}` : '未填写',
      hint: goal ? `${goal.goal_type} · ${goal.daily_calories} kcal/日` : '填了才能校验营养与花销',
      done: Boolean(budget) && Boolean(goal),
      to: '/preferences?focus=goal',
    },
    {
      key: 'automation',
      icon: <BellOutlined />,
      title: '自动化',
      value: automation?.feishu.configured
        ? automation.feishu.source === 'user'
          ? '已配置'
          : '用部署默认'
        : '未配置',
      hint: automation?.feishu.configured
        ? `工作日 ${automation.reminders.daily_menu_push} 推送菜单 · 点开可改飞书参数`
        : '点开填写飞书应用参数, 配好就能推送菜单',
      done: Boolean(automation?.feishu.configured),
      to: '',
    },
    {
      key: 'fridge',
      icon: <ShoppingOutlined />,
      title: '按冰箱重排本周',
      value: rebuilding ? '重排中…' : '一键',
      hint: '先把冰箱现有食材排进菜单, 再算出这一周要补的采购清单',
      done: true,
      to: '',
      action: handleFridgeRebuild,
    },
  ]

  return (
    <div className="me-panel">
      <div className="drawer-head">
        <div>
          <h2>我的</h2>
          <div className="card-sub">
            {user.name} · {user.open_id.startsWith('ou_') ? '飞书账号' : '本地账号'} ·
            饭决会按这些偏好做决定
          </div>
        </div>
      </div>

      <div className="card">
        <div className="settings">
          {groups.map((group) => (
            <button
              key={group.key}
              type="button"
              className="setting-row"
              onClick={() => {
                if (group.action) return group.action()
                return group.to ? onNavigate(group.to) : setShowAutomation((prev) => !prev)
              }}
            >
              <span className="setting-icon">{group.icon}</span>
              <span className="setting-copy">
                <b>{group.title}</b>
                <span>{group.hint}</span>
              </span>
              <span className="setting-value">
                {group.done ? `${group.value} ›` : `未设置 ›`}
              </span>
            </button>
          ))}
        </div>
      </div>

      {(showAutomation || automationError) && (
        <>
          <AutomationCard status={automation} error={automationError} />
          <FeishuConfigCard onChanged={refreshAutomation} />
        </>
      )}

      {fridgeSummary && (
        <Card>
          <div className="card-head">
            <div>
              <div className="card-title">按冰箱重排结果</div>
              <div className="card-sub">
                {fridgeSummary.cookable_now} 餐现在就能做 · {fridgeSummary.need_shopping} 餐需要补货
                {fridgeSummary.locked_items > 0
                  ? ` · ${fridgeSummary.locked_items} 餐已锁定没动`
                  : ''}
              </div>
            </div>
          </div>
          <div className="stack-actions">
            <PillButton variant="gray" block onClick={() => onNavigate('/shopping')}>
              去看这一周的采购清单
            </PillButton>
          </div>
        </Card>
      )}

      {/* 运行状态: V1.2.0 从首页搬过来的「今日流程时间线」 */}
      <RuntimeCard onNavigate={onNavigate} />

      <AppearanceCard />

      <div className="page-footnote">
        {brand.localDataNote}
        <br />
        当前部署: {typeof window !== 'undefined' ? window.location.host : '本地'}
      </div>

      <PillButton variant="gray" block onClick={handleLogout}>
        <LogoutOutlined /> 退出登录
      </PillButton>
    </div>
  )
}

/**
 * 运行状态 —— 「今天的自动流程」在 V1.2.0 从首页搬到这里
 *
 * 那是**系统**的自动化日志("8:00 菜单推送 已完成"), 不是**用户**要做的事。
 * 它在首页只会提醒用户"App 在替你跑东西", 而用户只关心"今晚吃啥"。
 * 唯一用途是排障, 所以收进「我的」并默认折叠, 展开了才去拉数据。
 */
const RuntimeCard: React.FC<{ onNavigate: (to: string) => void }> = ({ onNavigate }) => {
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState<TimelineEntry[] | null>(null)

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (!next || entries) return
    getToday()
      .then((view) => setEntries(view.timeline))
      .catch(() => setEntries([]))
  }

  return (
    <Card tight>
      <button type="button" className="set-row set-row--btn" onClick={toggle}>
        <div className="set-icon">
          <BellOutlined />
        </div>
        <div className="set-text">
          <b>运行状态</b>
          <span>今天的自动流程跑到哪一步了</span>
        </div>
        <div className="set-value">
          <b>{open ? '收起' : '展开'}</b>
        </div>
      </button>
      {open && entries ? (
        <div className="timeline">
          {entries.length === 0 ? (
            <div className="card-sub">今天还没有自动流程记录</div>
          ) : (
            entries.map((entry) => (
              <button
                key={entry.key}
                type="button"
                className="timeline-row"
                onClick={() => onNavigate(timelineTarget(entry))}
              >
                <span className={`state-dot ${TIMELINE_DOT[timelineTone(entry.status)]}`} />
                <div className="timeline-text">
                  <b>{entry.label}</b>
                  <span>{entry.detail}</span>
                </div>
                <span className="timeline-time">{entry.time || '完成时'}</span>
              </button>
            ))
          )}
        </div>
      ) : null}
    </Card>
  )
}

const TIMELINE_DOT: Record<string, string> = {
  ok: '',
  pending: 'is-pending',
  failed: 'is-failed',
  off: 'is-off',
}

function timelineTarget(entry: TimelineEntry): string {
  if (entry.key === 'menu_push') return '/me'
  if (entry.key === 'stock_check') return '/shopping'
  return '/menus'
}

const THEME_CHOICES: Array<{ key: ThemeName; label: string }> = [
  { key: 'auto', label: '自动' },
  { key: 'cream', label: '明亮' },
  { key: 'cool', label: '冷色' },
  { key: 'dark', label: '深色' },
]

const AppearanceCard: React.FC = () => {
  const theme = useThemeStore((s) => s.theme)
  const setTheme = useThemeStore((s) => s.setTheme)
  return (
    <>
      <div className="section-label">外观</div>
      <div className="card">
        <div className="card-title">跟随你的使用环境</div>
        <div className="card-sub">自动 = 跟随系统亮色/暗色</div>
        <div className="theme-row">
          {THEME_CHOICES.map((choice) => (
            <button
              key={choice.key}
              type="button"
              className={`theme-choice ${theme === choice.key ? 'active' : ''}`}
              onClick={() => setTheme(choice.key)}
            >
              {choice.label}
            </button>
          ))}
        </div>
      </div>
    </>
  )
}

const AutomationCard: React.FC<{ status: AutomationStatus | null; error: string }> = ({
  status,
  error,
}) => {
  if (error) {
    return (
      <Card tight>
        <Banner tone="warn" title="读不到机器人状态" text={error} />
      </Card>
    )
  }
  if (!status) return <LoadingStack rows={2} />

  const { feishu, scheduler, reminders, notifications } = status
  return (
    <Card tight>
      <div className="card-head">
        <div>
          <div className="card-title">飞书机器人</div>
          <div className="card-sub">
            {feishu.configured
              ? feishu.bound
                ? '已连接, 到点会把菜单推到你的飞书'
                : '应用已配置, 但当前账号不是飞书登录, 收不到推送'
              : '还没有配置飞书应用, 推送暂不可用'}
          </div>
        </div>
        <Chip tone={feishu.configured && feishu.bound ? 'green' : 'gray'}>
          {feishu.configured ? (feishu.bound ? '已连接' : '未绑定') : '未配置'}
        </Chip>
      </div>

      <div className="set-group">
        <div className="set-row">
          <div className="set-text">
            <b>定时推送</b>
            <span>
              工作日 {reminders.daily_menu_push} 推菜单 · {reminders.evening_check} 查库存
            </span>
          </div>
          <div className="set-value">
            <b>{scheduler.enabled ? '已开启' : '未开启'}</b>
            <span className={`state-dot ${scheduler.enabled ? '' : 'is-off'}`} />
          </div>
        </div>
        <div className="set-row">
          <div className="set-text">
            <b>最近一次推送</b>
            <span>
              {feishu.last_push_at
                ? `${feishu.last_push_at.replace('T', ' ').slice(0, 16)} · ${
                    feishu.last_push_status === 'sent' ? '已送达' : feishu.last_push_status || ''
                  }`
                : '还没有推送记录'}
            </span>
          </div>
        </div>
      </div>

      {notifications.length > 0 && (
        <div className="notif-list">
          {notifications.slice(0, 4).map((item) => (
            <div key={item.id} className="notif-row">
              <span className={`state-dot ${item.status === 'sent' ? '' : 'is-off'}`} />
              <div className="notif-text">
                <b>{item.title}</b>
                <span>{item.occurred_at.replace('T', ' ').slice(5, 16)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="page-footnote" style={{ marginTop: 8 }}>
        <SafetyOutlined /> {reminders.note}
        <br />
        开关由服务端配置控制, 这里只如实显示当前状态。
      </div>
    </Card>
  )
}

export default MePanel
