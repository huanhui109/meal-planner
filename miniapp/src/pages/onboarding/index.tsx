/**
 * 新用户引导 (audit T2.1 / F4)
 *
 * 3 步:
 *  1. 家庭人数 (1 / 2 / 3-4 / 5+)
 *  2. 菜系偏好 (家常 / 川湘 / 粤式 / 清淡 / 不挑)
 *  3. 引导生成第一份菜单
 *
 * 完成后写 mp_onboarded=true, 跳到今日页; 中途退出不算完成
 * 不依赖网络: 偏好暂时存本地, 完成后再让用户用 dev-login / 微信登录
 */
import { useState } from 'react'
import Taro from '@tarojs/taro'
import { Text, View } from '@tarojs/components'

import { PillButton } from '../../components/ui'
import { setOnboarded } from '../../lib/session'

const STORAGE_KEY = 'mp_onboarding_draft'

interface Draft {
  householdSize: 1 | 2 | 3 | 4 | null
  cuisine: 'homestyle' | 'spicy' | 'cantonese' | 'light' | 'flexible' | null
}

const DEFAULT_DRAFT: Draft = { householdSize: null, cuisine: null }

const HOUSEHOLD_OPTIONS: Array<{ value: 1 | 2 | 3 | 4; label: string }> = [
  { value: 1, label: '1 人' },
  { value: 2, label: '2 人' },
  { value: 3, label: '3-4 人' },
  { value: 4, label: '5+ 人' },
]

const CUISINE_OPTIONS: Array<{ value: Draft['cuisine']; label: string; hint: string }> = [
  { value: 'homestyle', label: '家常', hint: '三天不重样的简餐' },
  { value: 'spicy', label: '川湘', hint: '重口味, 怕辣慎选' },
  { value: 'cantonese', label: '粤式', hint: '清淡养胃' },
  { value: 'light', label: '清淡', hint: '蒸煮为主, 老人友好' },
  { value: 'flexible', label: '不挑', hint: '让 AI 自由发挥' },
]

export default function OnboardingPage() {
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [draft, setDraft] = useState<Draft>(DEFAULT_DRAFT)

  const persistDraft = (next: Draft) => {
    setDraft(next)
    try {
      Taro.setStorageSync(STORAGE_KEY, JSON.stringify(next))
    } catch {
      /* ignore */
    }
  }

  const handleFinish = () => {
    setOnboarded(true)
    try {
      Taro.removeStorageSync(STORAGE_KEY)
    } catch {
      /* ignore */
    }
    Taro.reLaunch({ url: '/pages/today/index' })
  }

  return (
    <View className="page">
      <View className="onboard">
        <View className="onboard__progress">
          <View
            className={`onboard__dot ${step >= 1 ? 'onboard__dot--active' : ''}`}
          />
          <View
            className={`onboard__dot ${step >= 2 ? 'onboard__dot--active' : ''}`}
          />
          <View
            className={`onboard__dot ${step >= 3 ? 'onboard__dot--active' : ''}`}
          />
          <Text className="onboard__step">{step} / 3</Text>
        </View>

        {step === 1 ? (
          <View className="onboard__step-body">
            <Text className="onboard__title">家里几口人吃饭?</Text>
            <Text className="onboard__hint">
              按每天实际吃饭的人数算, 关系到菜量和预算
            </Text>
            <View className="onboard__choices">
              {HOUSEHOLD_OPTIONS.map((opt) => (
                <View
                  key={opt.value}
                  className={`onboard__choice ${draft.householdSize === opt.value ? 'onboard__choice--active' : ''}`}
                  onClick={() => persistDraft({ ...draft, householdSize: opt.value })}
                >
                  <Text>{opt.label}</Text>
                </View>
              ))}
            </View>
            <PillButton
              block
              disabled={draft.householdSize == null}
              onClick={() => setStep(2)}
            >
              下一步
            </PillButton>
          </View>
        ) : null}

        {step === 2 ? (
          <View className="onboard__step-body">
            <Text className="onboard__title">想吃哪个菜系?</Text>
            <Text className="onboard__hint">
              可以多选; 不选就让 AI 全权发挥
            </Text>
            <View className="onboard__choices">
              {CUISINE_OPTIONS.map((opt) => (
                <View
                  key={opt.value ?? 'none'}
                  className={`onboard__choice onboard__choice--wide ${draft.cuisine === opt.value ? 'onboard__choice--active' : ''}`}
                  onClick={() => persistDraft({ ...draft, cuisine: opt.value })}
                >
                  <Text className="onboard__choice-label">{opt.label}</Text>
                  <Text className="onboard__choice-hint">{opt.hint}</Text>
                </View>
              ))}
            </View>
            <View style={{ display: 'flex', gap: 12 }}>
              <PillButton variant="ghost" onClick={() => setStep(1)}>
                上一步
              </PillButton>
              <PillButton block onClick={() => setStep(3)} disabled={draft.cuisine == null}>
                下一步
              </PillButton>
            </View>
          </View>
        ) : null}

        {step === 3 ? (
          <View className="onboard__step-body">
            <Text className="onboard__title">准备好了, 去生成菜单</Text>
            <Text className="onboard__hint">
              根据你刚才的选择, 我们已经可以生成第 1 份菜单了
              {'\n'}
              之后任何时候都能在「我的 → 家庭与厨房」改
            </Text>
            <View className="onboard__summary">
              <View className="onboard__summary-row">
                <Text className="onboard__summary-key">吃饭人数</Text>
                <Text className="onboard__summary-val">
                  {draft.householdSize ?? '-'} 人
                </Text>
              </View>
              <View className="onboard__summary-row">
                <Text className="onboard__summary-key">菜系偏好</Text>
                <Text className="onboard__summary-val">
                  {CUISINE_OPTIONS.find((opt) => opt.value === draft.cuisine)?.label ?? '-'}
                </Text>
              </View>
            </View>
            <View style={{ display: 'flex', gap: 12 }}>
              <PillButton variant="ghost" onClick={() => setStep(2)}>
                上一步
              </PillButton>
              <PillButton block onClick={handleFinish}>
                开始用
              </PillButton>
            </View>
          </View>
        ) : null}
      </View>
    </View>
  )
}
