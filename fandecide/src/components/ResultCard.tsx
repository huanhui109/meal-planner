import type { DecisionResult } from '@/types'
import { ClockIcon, FlameIcon, TagIcon, RainIcon, SnowIcon, SunIcon } from './Icon'

// 结果卡: 默认只露「餐次 + 菜名 + 一句话理由 + 图标化元信息」。
// 做法藏在底部 sheet, 不占首屏文字。

function WeatherIcon({ cond }: { cond?: string }) {
  if (cond === 'rain') return <RainIcon size={16} />
  if (cond === 'snow') return <SnowIcon size={16} />
  if (cond === 'sunny' || cond === 'hot') return <SunIcon size={16} />
  return null
}

export function ResultCard({
  result,
  loading,
  onRoll,
  onKeep,
  onSteps,
}: {
  result: DecisionResult
  loading: boolean
  onRoll: () => void
  onKeep: () => void
  onSteps: () => void
}) {
  const d = result.dish
  const weather = (result.weather?.condition as string | undefined) ?? undefined
  const hasMeta = d.cook_minutes || d.calories || d.cuisine || weather

  return (
    <div className="result">
      <div className="result-slot">{result.meal_slot_label || result.meal_slot}</div>
      <h1 className="dish-name">{d.name}</h1>
      {result.reason ? <div className="reason">{result.reason}</div> : null}

      {hasMeta ? (
        <div className="meta">
          {d.cook_minutes ? (
            <span className="chip">
              <ClockIcon size={16} />
              {d.cook_minutes}′
            </span>
          ) : null}
          {d.calories ? (
            <span className="chip">
              <FlameIcon size={16} />
              {d.calories}
            </span>
          ) : null}
          {d.cuisine ? (
            <span className="chip">
              <TagIcon size={16} />
              {d.cuisine}
            </span>
          ) : null}
          {weather ? <WeatherIcon cond={weather} /> : null}
        </div>
      ) : null}

      <div className="actions">
        <button className="link-btn" disabled={loading} onClick={onRoll}>
          换一个
        </button>
        <button className="link-btn" disabled={loading} onClick={onSteps}>
          做法
        </button>
        <button className="link-btn strong" disabled={loading} onClick={onKeep}>
          就这个
        </button>
      </div>
    </div>
  )
}
