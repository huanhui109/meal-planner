import { useEffect, useState } from 'react'
import {
  getCurrentMenu,
  markCookedMenuItem,
  rebuildMenu,
  replaceMenuItem,
  setLockMenuItem,
  undoCookedMenuItem,
} from '@/api/menus'
import { ApiError } from '@/api/client'
import type { MenuData, MenuMeal } from '@/types'
import { ClockIcon, FlameIcon, LockIcon, CheckIcon } from './Icon'
import { StepsSheet } from './StepsSheet'
import { useToast } from './Toast'

function todayISO(): string {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

export function WeekMenu({ onAuthFail }: { onAuthFail: () => void }) {
  const [menu, setMenu] = useState<MenuData | null>(null)
  const [selected, setSelected] = useState(0)
  const [loading, setLoading] = useState(true)
  const [sheet, setSheet] = useState<MenuMeal | null>(null)
  const { show, Toast } = useToast()

  async function load() {
    setLoading(true)
    try {
      const m = await getCurrentMenu()
      setMenu(m)
      const idx = m.days.findIndex((d) => d.date === todayISO())
      setSelected(idx >= 0 ? idx : 0)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        show('还没有本周菜单，点“重新排一周”先生成')
      } else if (e instanceof ApiError && e.status === 401) {
        onAuthFail()
      } else {
        show('菜单加载失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function regen() {
    setLoading(true)
    try {
      await rebuildMenu()
      await load()
      show('已按冰箱食材重排本周')
    } catch {
      show('重排失败，稍后再试')
      setLoading(false)
    }
  }

  async function replace(mealId: number) {
    if (!menu) return
    try {
      const m = await replaceMenuItem(menu.id, mealId)
      setMenu(m)
      show('已换一道')
    } catch {
      show('换菜失败')
    }
  }

  async function toggleLock(meal: MenuMeal) {
    if (!menu) return
    try {
      await setLockMenuItem(menu.id, meal.id, !meal.is_locked)
      await load()
      show(meal.is_locked ? '已解锁' : '已锁定')
    } catch {
      show('操作失败')
    }
  }

  async function toggleCook(meal: MenuMeal) {
    if (!menu) return
    try {
      if (meal.is_cooked) {
        await undoCookedMenuItem(menu.id, meal.id)
        await load()
        show('已撤销，库存已还原')
      } else {
        const res = await markCookedMenuItem(menu.id, meal.id)
        await load()
        const miss = res.missing.length
        show(miss ? `已标记完成，${miss} 样缺料` : '已标记完成并扣库存')
      }
    } catch {
      show('操作失败')
    }
  }

  const day = menu?.days[selected]
  const budgetLimit = menu?.budget?.budget_limit
  const estimated = menu?.totals.estimated_cost ?? 0

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>本周菜单</h1>
          <p>
            {menu
              ? `${menu.week_start_date} 起 · 先看每天，再改具体一餐`
              : '按冰箱食材自动编排，可逐餐调整'}
          </p>
        </div>
        <button className="button small" onClick={regen} disabled={loading}>
          重新排一周
        </button>
      </div>

      {!menu && loading ? (
        <div className="card empty-state">加载中…</div>
      ) : !menu ? (
        <div className="card empty-state">
          还没有本周菜单。点右上角“重新排一周”按冰箱现有食材生成一份。
        </div>
      ) : (
        <>
          <div className="week-summary">
            <div className="stat">
              <div className="stat-label">本周预算</div>
              <div className="stat-value">
                ¥{Math.round(estimated)}
                {budgetLimit ? <small style={{ display: 'inline' }}> / ¥{Math.round(budgetLimit)}</small> : null}
              </div>
              <div className="bar">
                <i style={{ width: budgetLimit ? `${Math.min(100, (estimated / budgetLimit) * 100)}%` : '0%' }} />
              </div>
              <small>{budgetLimit ? '花超了会标红' : '未设置预算上限'}</small>
            </div>
            <div className="stat">
              <div className="stat-label">覆盖天数</div>
              <div className="stat-value">
                {menu.totals.day_count} <small style={{ display: 'inline' }}>天</small>
              </div>
              <small>{menu.totals.unpriced_items} 餐未计价</small>
            </div>
            <div className="stat">
              <div className="stat-label">本周进度</div>
              <div className="stat-value">
                {menu.totals.cooked_count} / {menu.totals.meal_count}
              </div>
              <small>做完后自动扣库存</small>
            </div>
          </div>

          <div className="days">
            {menu.days.map((d, i) => {
              const isToday = d.date === todayISO()
              return (
                <button
                  key={d.date}
                  className={'day' + (i === selected ? ' active' : '')}
                  onClick={() => setSelected(i)}
                >
                  <span>{d.weekday}</span>
                  <b>{d.date.slice(5)}</b>
                  {isToday ? <i className="dot" /> : null}
                </button>
              )
            })}
          </div>

          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">
                  {day?.weekday} · {day?.date}
                </div>
                <div className="card-sub">
                  {day ? `${day.meals.length} 餐 · 预计 ¥${Math.round(day.estimated_cost)}` : ''}
                </div>
              </div>
              <span className="tag good">{day?.date === todayISO() ? '今天' : '已安排'}</span>
            </div>
            <div className="meal-list">
              {day?.meals.map((meal) => (
                <div key={meal.id} className={'meal-row' + (meal.is_cooked ? ' done' : '')}>
                  <div className="meal-slot">{meal.meal_label}</div>
                  <div className="meal-info">
                    <b>{meal.recipe?.name ?? '（待定）'}</b>
                    <div className="meal-meta">
                      {meal.recipe?.cook_minutes ? (
                        <span>
                          <ClockIcon size={13} /> {meal.recipe.cook_minutes}′
                        </span>
                      ) : null}
                      {meal.recipe?.calories ? (
                        <span>
                          <FlameIcon size={13} /> {meal.recipe.calories}
                        </span>
                      ) : null}
                      {meal.is_locked ? (
                        <span className="lock-tag">
                          <LockIcon size={12} /> 已锁定
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="meal-actions">
                    <button className="button small" onClick={() => replace(meal.id)}>
                      换一道
                    </button>
                    <button className="button small" onClick={() => toggleLock(meal)}>
                      {meal.is_locked ? '解锁' : '锁定'}
                    </button>
                    <button
                      className={'button small' + (meal.is_cooked ? '' : ' primary')}
                      onClick={() => toggleCook(meal)}
                    >
                      {meal.is_cooked ? (
                        <>
                          <CheckIcon size={13} /> 已做·撤销
                        </>
                      ) : (
                        '做完了'
                      )}
                    </button>
                    {meal.recipe ? (
                      <button className="button small" onClick={() => setSheet(meal)}>
                        做法
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {sheet?.recipe ? (
        <StepsSheet
          title={sheet.recipe.name}
          steps={sheet.recipe.steps}
          ingredients={sheet.recipe.ingredients.map((g) => ({
            name: g.name,
            quantity: g.quantity,
            unit: g.unit,
          }))}
          onClose={() => setSheet(null)}
        />
      ) : null}
      {Toast}
    </div>
  )
}
