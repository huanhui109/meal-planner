import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Empty, Progress, Skeleton, Tag, message } from 'antd'
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import PageHeader from '../components/PageHeader'
import { currentWeekStart, getCurrentMenu } from '../api/menu'
import { listInventory } from '../api/inventory'
import { useMenuGeneration } from '../hooks/useMenuGeneration'
import type { CurrentUser, InventoryItem, MenuDetail, MealDetail } from '../types'

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function todayIso(): string {
  const now = new Date()
  const month = `${now.getMonth() + 1}`.padStart(2, '0')
  const day = `${now.getDate()}`.padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

const Dashboard: React.FC<{ user: CurrentUser }> = ({ user }) => {
  const navigate = useNavigate()
  const [menu, setMenu] = useState<MenuDetail | null>(null)
  const [inventory, setInventory] = useState<InventoryItem[]>([])
  const [expiringCount, setExpiringCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [noMenu, setNoMenu] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [menuResult, inventoryResult] = await Promise.allSettled([
        getCurrentMenu(),
        listInventory(),
      ])
      if (menuResult.status === 'fulfilled') {
        setMenu(menuResult.value)
        setNoMenu(false)
      } else {
        setMenu(null)
        setNoMenu(true)
      }
      if (inventoryResult.status === 'fulfilled') {
        setInventory(inventoryResult.value.items)
        setExpiringCount(inventoryResult.value.expiring_count)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const generation = useMenuGeneration(() => {
    message.success('菜单已生成')
    load()
  })

  const today = todayIso()
  const todayDay = menu?.days.find((day) => day.date === today) ?? menu?.days[0]
  const budgetLimit = menu?.budget.budget_limit ?? 0
  const spent = menu?.budget.total_estimated ?? 0
  const budgetPercent =
    budgetLimit > 0 ? Math.min(100, Math.round((spent / budgetLimit) * 100)) : 0

  if (loading) {
    return (
      <div className="page">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    )
  }

  return (
    <div className="page">
      <PageHeader
        title={`你好, ${user.name}`}
        subtitle={`本周菜单从 ${menu?.week_start_date ?? currentWeekStart()} 开始`}
        extra={
          <Button
            icon={menu ? <ReloadOutlined /> : <ThunderboltOutlined />}
            type={menu ? 'default' : 'primary'}
            loading={generation.running}
            onClick={() => generation.start(currentWeekStart(), Boolean(menu))}
          >
            {menu ? '重新生成' : '生成菜单'}
          </Button>
        }
      />

      {generation.error && (
        <Alert type="error" showIcon message={generation.error} className="page-alert" closable />
      )}
      {generation.running && (
        <Alert
          type="info"
          showIcon
          className="page-alert"
          message="AI 正在生成菜单, 通常需要 1-2 分钟, 可以先去其他页面"
        />
      )}

      {noMenu && !generation.running && (
        <div className="card">
          <Empty description="本周还没有菜单">
            <Button type="primary" loading={generation.running} onClick={() => generation.start()}>
              立即生成
            </Button>
          </Empty>
        </div>
      )}

      {menu && (
        <>
          <div className="stat-grid">
            <div className="card stat-card">
              <div className="stat-label">本周预估花费</div>
              <div className="stat-value">
                ¥{spent.toFixed(0)}
                <span className="stat-unit">/ {budgetLimit ? `¥${budgetLimit.toFixed(0)}` : '未设预算'}</span>
              </div>
              {budgetLimit > 0 && (
                <Progress
                  percent={budgetPercent}
                  showInfo={false}
                  strokeColor={menu.budget.passed ? 'var(--vibe-success)' : 'var(--vibe-danger)'}
                  size="small"
                />
              )}
              {!menu.budget.passed && <div className="stat-hint danger">已超预算</div>}
            </div>

            <div className="card stat-card">
              <div className="stat-label">营养达标</div>
              <div className="stat-value">
                {menu.nutrition.passed ? '达标' : '有偏离'}
              </div>
              <div className="stat-hint">
                日均 {menu.nutrition.weekly_avg_calories.toFixed(0)} kcal
                {menu.nutrition.target_calories ? ` / 目标 ${menu.nutrition.target_calories}` : ''}
              </div>
            </div>

            <div className="card stat-card">
              <div className="stat-label">冰箱库存</div>
              <div className="stat-value">{inventory.length} 项</div>
              <div className="stat-hint">
                {expiringCount > 0 ? `${expiringCount} 项临期` : '暂无临期食材'}
              </div>
            </div>

            <div className="card stat-card">
              <div className="stat-label">本周进度</div>
              <div className="stat-value">
                {menu.totals.cooked_count}/{menu.totals.meal_count} 餐
              </div>
              <div className="stat-hint">{menu.totals.day_count} 天菜单</div>
            </div>
          </div>

          <div className="card">
            <div className="card-title-row">
              <div className="card-title">
                {todayDay ? `${WEEKDAY_LABELS[todayDay.weekday]}的餐次` : '今日餐次'}
              </div>
              <Button type="link" onClick={() => navigate('/menus')}>
                查看整周
              </Button>
            </div>
            {todayDay && todayDay.meals.length > 0 ? (
              <div className="meal-list">
                {todayDay.meals.map((meal) => (
                  <MealRow key={meal.id} meal={meal} />
                ))}
              </div>
            ) : (
              <Empty description="今天没有排餐" />
            )}
          </div>

          {menu.nutrition.issues.length > 0 && (
            <Alert
              type="warning"
              showIcon
              className="page-alert"
              message="营养提醒"
              description={
                <ul className="alert-list">
                  {menu.nutrition.issues.slice(0, 3).map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              }
            />
          )}
          {menu.budget.suggestions.length > 0 && (
            <Alert
              type="warning"
              showIcon
              className="page-alert"
              message="预算提醒"
              description={
                <ul className="alert-list">
                  {menu.budget.suggestions.slice(0, 3).map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
              }
            />
          )}
        </>
      )}
    </div>
  )
}

const MealRow: React.FC<{ meal: MealDetail }> = ({ meal }) => (
  <div className="meal-row">
    <div className="meal-row-main">
      <div className="meal-row-name">
        {meal.recipe?.name ?? '未安排'}
        {meal.is_locked && <Tag className="tag-soft">已锁定</Tag>}
        {meal.is_cooked && <Tag color="green">已做</Tag>}
      </div>
      <div className="meal-row-meta">
        <span className="meal-badge">{meal.meal_label}</span>
        {meal.recipe?.cook_minutes ? <span>{meal.recipe.cook_minutes} 分钟</span> : null}
        {meal.recipe?.calories ? <span>{meal.recipe.calories} kcal</span> : null}
        {meal.estimated_cost ? <span>≈¥{meal.estimated_cost.toFixed(1)}</span> : null}
      </div>
    </div>
  </div>
)

export default Dashboard
