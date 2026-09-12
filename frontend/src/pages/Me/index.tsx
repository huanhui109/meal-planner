/**
 * 「我的」- 偏好四组 + 机器人状态
 *
 * 结构照参考稿: 一行一个分组, 右侧是"当前值 + 状态点", 点进去才是表单。
 * 这样抽屉里一眼能看出"哪几项还没填", 不用翻五个表单找。
 */
import React, { useCallback, useEffect, useState } from 'react'
import { message } from 'antd'
import {
  ArrowRightOutlined,
  BellOutlined,
  FireOutlined,
  HomeOutlined,
  LogoutOutlined,
  SafetyOutlined,
  WalletOutlined,
} from '@ant-design/icons'
import { Banner, Card, Chip, LoadingStack, PillButton } from '../../components/ui'
import { LogoLockup } from '../../components/ui/logo'
import { getAutomationStatus } from '../../api/automation'
import FeishuConfigCard from './FeishuConfigCard'
import { logout } from '../../api/auth'
import { usePreferenceStore } from '../../stores/usePreferenceStore'
import { useThemeStore } from '../../stores/useThemeStore'
import { brand } from '@shared/brand'
import { formatMoney } from '@shared/format'
import type { AutomationStatus, CurrentUser } from '../../types'

interface MePanelProps {
  user: CurrentUser
  onNavigate: (to: string) => void
}

const MePanel: React.FC<MePanelProps> = ({ user, onNavigate }) => {
  const { summary, loaded, loading, fetchSummary } = usePreferenceStore()
  const [automation, setAutomation] = useState<AutomationStatus | null>(null)
  const [automationError, setAutomationError] = useState('')
  const [showAutomation, setShowAutomation] = useState(false)

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

  const groups = [
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
  ]

  return (
    <div className="me-panel">
      <div className="me-head">
        <LogoLockup subtitle="" />
        <div className="me-user">
          <b>{user.name}</b>
          <span>{user.open_id.startsWith('ou_') ? '飞书账号' : '本地账号'}</span>
        </div>
      </div>

      <Card tight>
        <div className="set-group">
          {groups.map((group) => (
            <button
              key={group.key}
              type="button"
              className="set-row set-row--btn"
              onClick={() =>
                group.to ? onNavigate(group.to) : setShowAutomation((prev) => !prev)
              }
            >
              <div className="set-icon">{group.icon}</div>
              <div className="set-text">
                <b>{group.title}</b>
                <span>{group.hint}</span>
              </div>
              <div className="set-value">
                <b>{group.value}</b>
                <span className={`state-dot ${group.done ? '' : 'is-off'}`} />
              </div>
              <ArrowRightOutlined className="set-arrow" />
            </button>
          ))}
        </div>
      </Card>

      {(showAutomation || automationError) && (
        <>
          <AutomationCard status={automation} error={automationError} />
          <FeishuConfigCard onChanged={refreshAutomation} />
        </>
      )}

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

const AppearanceCard: React.FC = () => {
  const theme = useThemeStore((s) => s.theme)
  const setTheme = useThemeStore((s) => s.setTheme)
  return (
    <Card tight>
      <div className="card-head">
        <div className="card-title">外观</div>
        <Chip tone="gray">两套随时可切</Chip>
      </div>
      <div className="set-group">
        <button
          type="button"
          className="set-row set-row--btn"
          onClick={() => setTheme('dark')}
        >
          <div className="set-text">
            <b>深色 · 黑色胶囊</b>
            <span>沿用冷灰底, 主按钮仍是品牌黑</span>
          </div>
          <span className={`state-dot ${theme === 'dark' ? '' : 'is-off'}`} />
        </button>
        <button
          type="button"
          className="set-row set-row--btn"
          onClick={() => setTheme('light')}
        >
          <div className="set-text">
            <b>明亮 · 暖色奶油</b>
            <span>奶油底 + 暖橙提示色, 更接近早餐店氛围</span>
          </div>
          <span className={`state-dot ${theme === 'light' ? '' : 'is-off'}`} />
        </button>
      </div>
    </Card>
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
