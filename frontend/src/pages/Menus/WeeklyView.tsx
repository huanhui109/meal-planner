import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Button,
  Collapse,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Skeleton,
  Space,
  Tag,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  LockOutlined,
  ShoppingCartOutlined,
  SwapOutlined,
  UnlockOutlined,
} from '@ant-design/icons'
import PageHeader from '../../components/PageHeader'
import {
  confirmMenu,
  currentWeekStart,
  getCurrentMenu,
  lockMenuItem,
  markItemCooked,
  replaceMenuItem,
  unlockMenuItem,
} from '../../api/menu'
import { useMenuGeneration } from '../../hooks/useMenuGeneration'
import type { MealDetail, MenuDetail, MenuDay } from '../../types'

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

const WeeklyView: React.FC = () => {
  const navigate = useNavigate()
  const [menu, setMenu] = useState<MenuDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyItemId, setBusyItemId] = useState<number | null>(null)
  const [replaceTarget, setReplaceTarget] = useState<MealDetail | null>(null)
  const [replacing, setReplacing] = useState(false)
  const [form] = Form.useForm()

  const menuId = menu?.id

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setMenu(await getCurrentMenu())
    } catch {
      setMenu(null)
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

  const withItem = async (itemId: number, action: () => Promise<void>, successText: string) => {
    setBusyItemId(itemId)
    try {
      await action()
      message.success(successText)
      if (menuId) setMenu(await getCurrentMenu())
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setBusyItemId(null)
    }
  }

  const handleLockToggle = (meal: MealDetail) =>
    withItem(
      meal.id,
      async () => {
        if (!menuId) return
        if (meal.is_locked) await unlockMenuItem(menuId, meal.id)
        else await lockMenuItem(menuId, meal.id)
      },
      meal.is_locked ? '已解锁' : '已锁定, 重生成时不会改动',
    )

  const handleCooked = async (meal: MealDetail) => {
    if (!menuId) return
    setBusyItemId(meal.id)
    try {
      const result = await markItemCooked(menuId, meal.id)
      if (result.missing.length > 0) {
        message.warning(`已扣减库存, 但有 ${result.missing.length} 项食材不足`)
      } else if (result.consumed.length > 0) {
        message.success(`已扣减 ${result.consumed.length} 项库存`)
      } else {
        message.success('已标记完成 (该菜品没有可扣减的库存)')
      }
      setMenu(await getCurrentMenu())
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setBusyItemId(null)
    }
  }

  const submitReplace = async () => {
    if (!menuId || !replaceTarget) return
    try {
      const values = await form.validateFields()
      setReplacing(true)
      const updated = await replaceMenuItem(menuId, replaceTarget.id, {
        recipe_name: values.recipe_name,
        calories: values.calories ?? 0,
        cook_minutes: values.cook_minutes ?? 20,
        steps: values.steps ?? '',
      })
      setMenu(updated)
      message.success('已替换这一餐')
      setReplaceTarget(null)
      form.resetFields()
    } catch (err) {
      if (err instanceof Error) message.error(err.message)
    } finally {
      setReplacing(false)
    }
  }

  const handleConfirm = async () => {
    if (!menuId) return
    try {
      await confirmMenu(menuId)
      message.success('已确认本周菜单')
      setMenu(await getCurrentMenu())
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  if (loading) {
    return (
      <div className="page">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    )
  }

  if (!menu) {
    return (
      <div className="page">
        <PageHeader title="本周菜单" subtitle="还没有生成菜单" />
        {generation.error && <Alert type="error" showIcon message={generation.error} className="page-alert" />}
        <div className="card">
          <Empty description="本周还没有菜单">
            <Space>
              <Button onClick={() => navigate('/preferences')}>先完善偏好</Button>
              <Button type="primary" loading={generation.running} onClick={() => generation.start()}>
                生成菜单
              </Button>
            </Space>
          </Empty>
        </div>
      </div>
    )
  }

  const weekEnd = menu.days.length > 0 ? menu.days[menu.days.length - 1].date : menu.week_start_date

  return (
    <div className="page">
      <PageHeader
        title="本周菜单"
        subtitle={`${menu.week_start_date} ~ ${weekEnd} · 预估 ¥${menu.totals.estimated_cost.toFixed(0)}`}
        extra={
          <Space wrap>
            <Button icon={<ShoppingCartOutlined />} onClick={() => navigate('/shopping')}>
              采购清单
            </Button>
            <Button
              loading={generation.running}
              onClick={() => generation.start(currentWeekStart(), true)}
            >
              重新生成
            </Button>
            {menu.status === 'draft' && (
              <Button type="primary" onClick={handleConfirm}>
                确认菜单
              </Button>
            )}
          </Space>
        }
      />

      {generation.error && <Alert type="error" showIcon message={generation.error} className="page-alert" closable />}
      {generation.running && (
        <Alert
          type="info"
          showIcon
          className="page-alert"
          message="AI 正在生成菜单, 通常需要 1-2 分钟, 可以离开本页"
        />
      )}
      {menu.totals.unpriced_items > 0 && (
        <Alert
          type="warning"
          showIcon
          className="page-alert"
          message={`${menu.totals.unpriced_items} 项食材缺少参考单价, 预估成本可能偏低`}
        />
      )}

      <div className="day-list">
        {menu.days.map((day) => (
          <DayCard
            key={day.date}
            day={day}
            busyItemId={busyItemId}
            onLockToggle={handleLockToggle}
            onCooked={handleCooked}
            onReplace={setReplaceTarget}
          />
        ))}
      </div>

      <Modal
        title={`替换「${replaceTarget?.recipe?.name ?? ''}」`}
        open={Boolean(replaceTarget)}
        onCancel={() => setReplaceTarget(null)}
        onOk={submitReplace}
        confirmLoading={replacing}
        okText="替换"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="recipe_name"
            label="新菜名"
            rules={[{ required: true, message: '请输入菜名' }]}
          >
            <Input placeholder="例如: 番茄牛腩" />
          </Form.Item>
          <Space style={{ width: '100%' }} size="large">
            <Form.Item name="calories" label="热量 (kcal)">
              <InputNumber min={0} max={3000} placeholder="350" />
            </Form.Item>
            <Form.Item name="cook_minutes" label="烹饪时间 (分钟)">
              <InputNumber min={1} max={300} placeholder="20" />
            </Form.Item>
          </Space>
          <Form.Item name="steps" label="做法 (可选)">
            <Input.TextArea rows={3} placeholder="简要步骤" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

interface DayCardProps {
  day: MenuDay
  busyItemId: number | null
  onLockToggle: (meal: MealDetail) => void
  onCooked: (meal: MealDetail) => void
  onReplace: (meal: MealDetail) => void
}

const DayCard: React.FC<DayCardProps> = ({ day, busyItemId, onLockToggle, onCooked, onReplace }) => (
  <div className="card day-card">
    <div className="day-card-head">
      <div className="day-card-title">
        {WEEKDAY_LABELS[day.weekday]}
        <span className="day-card-date">{day.date.slice(5)}</span>
        {day.day_type === 'weekend' && <Tag className="tag-soft">周末</Tag>}
      </div>
      <div className="day-card-cost">≈¥{day.estimated_cost.toFixed(1)}</div>
    </div>

    {day.meals.length === 0 ? (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这一天没有排餐" />
    ) : (
      <div className="meal-list">
        {day.meals.map((meal) => (
          <div key={meal.id} className="meal-block">
            <div className="meal-block-head">
              <div>
                <div className="meal-block-name">
                  <span className="meal-badge">{meal.meal_label}</span>
                  {meal.recipe?.name ?? '未安排'}
                  {meal.is_locked && <Tag className="tag-soft">已锁定</Tag>}
                  {meal.is_cooked && <Tag color="green">已做</Tag>}
                </div>
                <div className="meal-row-meta">
                  {meal.recipe?.cook_minutes ? <span>{meal.recipe.cook_minutes} 分钟</span> : null}
                  {meal.recipe?.calories ? <span>{meal.recipe.calories} kcal</span> : null}
                  {meal.estimated_cost ? <span>≈¥{meal.estimated_cost.toFixed(1)}</span> : null}
                </div>
              </div>
              <Space size={4} wrap className="meal-actions">
                <Button
                  size="small"
                  type="text"
                  icon={<SwapOutlined />}
                  onClick={() => onReplace(meal)}
                >
                  换一道
                </Button>
                <Button
                  size="small"
                  type="text"
                  icon={meal.is_locked ? <UnlockOutlined /> : <LockOutlined />}
                  loading={busyItemId === meal.id}
                  onClick={() => onLockToggle(meal)}
                >
                  {meal.is_locked ? '解锁' : '锁定'}
                </Button>
                <Button
                  size="small"
                  type="text"
                  icon={<CheckCircleOutlined />}
                  disabled={meal.is_cooked}
                  loading={busyItemId === meal.id}
                  onClick={() => onCooked(meal)}
                >
                  {meal.is_cooked ? '已完成' : '标记已做'}
                </Button>
              </Space>
            </div>

            {meal.recipe && meal.recipe.ingredients.length > 0 && (
              <Collapse
                ghost
                size="small"
                items={[
                  {
                    key: meal.id,
                    label: `食材 (${meal.recipe.ingredients.length})`,
                    children: (
                      <>
                        <ul className="ingredient-list">
                          {meal.recipe.ingredients.map((ingredient) => (
                            <li key={`${meal.id}-${ingredient.name}`}>
                              <span>{ingredient.name}</span>
                              <span className="ingredient-amount">
                                {ingredient.quantity != null
                                  ? `${ingredient.quantity}${ingredient.unit}`
                                  : '适量'}
                              </span>
                            </li>
                          ))}
                        </ul>
                        {meal.recipe.steps && <div className="recipe-steps">{meal.recipe.steps}</div>}
                      </>
                    ),
                  },
                ]}
              />
            )}
          </div>
        ))}
      </div>
    )}
  </div>
)

export default WeeklyView
