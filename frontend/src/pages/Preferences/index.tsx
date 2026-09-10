import React, { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { message } from 'antd'
import { Banner, Card, LoadingStack, PageHead } from '../../components/ui'
import { usePreferenceStore } from '../../stores/usePreferenceStore'
import HouseholdForm from './HouseholdForm'
import DietForm from './DietForm'
import AllergyForm from './AllergyForm'
import HealthGoalForm from './HealthGoalForm'
import BudgetForm from './BudgetForm'

const Preferences: React.FC = () => {
  const { summary, loaded, loading, fetchSummary } = usePreferenceStore()
  const [params] = useSearchParams()
  const focus = params.get('focus')

  useEffect(() => {
    fetchSummary().catch((error: Error) => message.error(error.message))
  }, [fetchSummary])

  // 从「我的」抽屉点进来时自动滚到对应分组, 少一次翻找
  useEffect(() => {
    if (!focus || !loaded) return
    const target = document.getElementById(`focus-${focus}`)
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [focus, loaded])

  const missing: string[] = []
  if (summary && !summary.household) missing.push('家庭与厨房')
  if (summary && !summary.diet_preference) missing.push('口味偏好')
  if (summary && !summary.allergy_restriction) missing.push('过敏与忌口')
  if (summary && !summary.health_goal) missing.push('健康目标')
  if (summary && !summary.budget) missing.push('预算')

  const ready = missing.length === 0

  return (
    <div className="page">
      <PageHead
        title="偏好设置"
        subtitle={
          ready
            ? '偏好已填齐, 每次生成前都会按这些约束校验'
            : '填得越细, 生成的菜单越贴合你的习惯; 每张卡改完点一次保存'
        }
      />

      {!loaded && loading ? (
        <LoadingStack rows={5} />
      ) : (
        <>
          {missing.length > 0 ? (
            <Banner
              title={`还差 ${missing.length} 项没填`}
              text={`${missing.join(' / ')} · 至少填好家庭与预算, 生成结果才有准头`}
            />
          ) : (
            <Banner
              tone="accent"
              title="偏好已就绪"
              text="AI 生成菜单时会同时校验营养比例、预算上限和过敏源"
            />
          )}

          <Card tight>
            <div className="set-group">
              <PreferenceRow
                icon="👨‍👩‍👧"
                title="家庭与厨房"
                value={
                  summary?.household
                    ? `${summary.household.member_count} 人 · 每日 ${summary.household.meals_per_day} 餐`
                    : '未填写'
                }
                done={Boolean(summary?.household)}
              />
              <PreferenceRow
                icon="🍽️"
                title="口味与偏好"
                value={
                  summary?.diet_preference
                    ? `${(summary.diet_preference.cuisines ?? []).join(' · ') || '不限菜系'}`
                    : '未填写'
                }
                done={Boolean(summary?.diet_preference)}
              />
              <PreferenceRow
                icon="⚠️"
                title="过敏与忌口"
                value={
                  summary?.allergy_restriction
                    ? `过敏 ${(summary.allergy_restriction.allergens ?? []).length} 项 · 忌口 ${(summary.allergy_restriction.avoid_ingredients ?? []).length} 项`
                    : '未填写'
                }
                done={Boolean(summary?.allergy_restriction)}
              />
              <PreferenceRow
                icon="💪"
                title="目标与比例"
                value={
                  summary?.health_goal
                    ? `${summary.health_goal.goal_type} · ${summary.health_goal.daily_calories} kcal/日`
                    : '未填写'
                }
                done={Boolean(summary?.health_goal)}
              />
              <PreferenceRow
                icon="💰"
                title="预算"
                value={
                  summary?.budget
                    ? `工作日 ¥${summary.budget.weekday_daily_budget} · 周末 ¥${summary.budget.weekend_daily_budget}`
                    : '未填写'
                }
                done={Boolean(summary?.budget)}
              />
            </div>
          </Card>

          <section id="focus-household" className="focus-anchor">
            <HouseholdForm />
          </section>
          <section id="focus-taste" className="focus-anchor">
            <DietForm />
            <AllergyForm />
          </section>
          <section id="focus-goal" className="focus-anchor">
            <HealthGoalForm />
            <BudgetForm />
          </section>
        </>
      )}

      <div className="page-footnote">
        AI 只会把这些信息用于生成菜单, 不会对外分享。
      </div>
    </div>
  )
}

const PreferenceRow: React.FC<{
  icon: string
  title: string
  value: string
  done: boolean
}> = ({ icon, title, value, done }) => (
  <div className="set-row">
    <div className="set-icon">{icon}</div>
    <div className="set-text">
      <b>{title}</b>
      <span>{value}</span>
    </div>
    <span className={`state-dot ${done ? '' : 'is-off'}`} />
  </div>
)

export default Preferences
