import React, { useEffect } from 'react'
import { Alert, Skeleton, message } from 'antd'
import PageHeader from '../../components/PageHeader'
import { usePreferenceStore } from '../../stores/usePreferenceStore'
import HouseholdForm from './HouseholdForm'
import DietForm from './DietForm'
import AllergyForm from './AllergyForm'
import HealthGoalForm from './HealthGoalForm'
import BudgetForm from './BudgetForm'

const Preferences: React.FC = () => {
  const { summary, loaded, loading, fetchSummary } = usePreferenceStore()

  useEffect(() => {
    fetchSummary().catch((error: Error) => message.error(error.message))
  }, [fetchSummary])

  return (
    <div className="page">
      <PageHeader
        title="偏好设置"
        subtitle="AI 会根据这些信息生成菜单, 填得越细越贴合你的习惯"
      />

      {!loaded && loading ? (
        <div className="card">
          <Skeleton active paragraph={{ rows: 5 }} />
        </div>
      ) : (
        <>
          {!summary?.household && (
            <Alert
              type="info"
              showIcon
              className="page-alert"
              message="还没有填写偏好, 建议至少设置家庭人数、忌口与预算, 生成结果会更准确"
            />
          )}
          <HouseholdForm />
          <DietForm />
          <AllergyForm />
          <HealthGoalForm />
          <BudgetForm />
        </>
      )}
    </div>
  )
}

export default Preferences
