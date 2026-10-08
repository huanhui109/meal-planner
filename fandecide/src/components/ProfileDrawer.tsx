import { useEffect, useMemo, useState } from 'react'
import {
  getPreferenceSummary,
  updateAllergy,
  updateBudget,
  updateDiet,
  updateHealthGoal,
  updateHousehold,
} from '@/api/preferences'
import type {
  CurrentUser,
  PreferenceSummary,
  HouseholdPref,
  DietPref,
  AllergyPref,
  HealthGoalPref,
  BudgetPref,
} from '@/types'
import { CloseIcon } from './Icon'
import { useToast } from './Toast'

type GroupKey = 'household' | 'diet' | 'allergy' | 'health_goal' | 'budget'

interface FieldDef {
  name: string
  label: string
  type: 'number' | 'text' | 'list'
}

const GROUPS: { key: GroupKey; label: string; icon: string; fields: FieldDef[] }[] = [
  {
    key: 'household',
    label: '家庭与厨房',
    icon: '家',
    fields: [
      { name: 'member_count', label: '人数', type: 'number' },
      { name: 'meals_per_day', label: '每天餐数', type: 'number' },
      { name: 'kitchen_equipments', label: '厨具（逗号分隔）', type: 'list' },
      { name: 'weekday_cook_minutes', label: '工作日做饭时长(min)', type: 'number' },
      { name: 'weekend_cook_minutes', label: '周末做饭时长(min)', type: 'number' },
    ],
  },
  {
    key: 'diet',
    label: '口味与忌口',
    icon: '味',
    fields: [
      { name: 'cuisines', label: '喜欢的菜系（逗号分隔）', type: 'list' },
      { name: 'spice_level', label: '辣度（如：少辣）', type: 'text' },
      { name: 'flavor_preference', label: '口味偏好', type: 'text' },
      { name: 'staple_preference', label: '主食偏好', type: 'text' },
    ],
  },
  {
    key: 'allergy',
    label: '过敏与忌口',
    icon: '忌',
    fields: [
      { name: 'allergens', label: '过敏源（逗号分隔）', type: 'list' },
      { name: 'avoid_ingredients', label: '忌口食材（逗号分隔）', type: 'list' },
      { name: 'dietary_restrictions', label: '饮食限制', type: 'text' },
    ],
  },
  {
    key: 'health_goal',
    label: '目标与预算',
    icon: '衡',
    fields: [
      { name: 'goal_type', label: '目标类型', type: 'text' },
      { name: 'daily_calories', label: '每日热量(kcal)', type: 'number' },
      { name: 'protein_pct', label: '蛋白占比(%)', type: 'number' },
      { name: 'carb_pct', label: '碳水占比(%)', type: 'number' },
      { name: 'fat_pct', label: '脂肪占比(%)', type: 'number' },
    ],
  },
  {
    key: 'budget',
    label: '预算设置',
    icon: '预',
    fields: [
      { name: 'weekday_daily_budget', label: '工作日预算/天', type: 'number' },
      { name: 'weekend_daily_budget', label: '周末预算/天', type: 'number' },
      { name: 'weekly_cap', label: '每周上限', type: 'number' },
      { name: 'min_meal_budget', label: '单餐下限', type: 'number' },
    ],
  },
]

const API_MAP: Record<GroupKey, (d: Record<string, unknown>) => Promise<unknown>> = {
  household: updateHousehold,
  diet: updateDiet,
  allergy: updateAllergy,
  health_goal: updateHealthGoal,
  budget: updateBudget,
}

function subtitleFor(key: GroupKey, s: PreferenceSummary): string {
  const g = s[key]
  if (!g) return '未设置'
  if (key === 'household') {
    const h = g as HouseholdPref
    return `${h.member_count} 人 · ${(h.kitchen_equipments || []).join('/') || '厨具未设'}`
  }
  if (key === 'diet') {
    const d = g as DietPref
    return `${(d.cuisines || []).join('/') || '菜系未设'} · ${d.spice_level || '辣度未设'}`
  }
  if (key === 'allergy') {
    const a = g as AllergyPref
    return `${(a.avoid_ingredients || []).join('/') || '无忌口'}`
  }
  if (key === 'health_goal') {
    const h = g as HealthGoalPref
    return `${h.goal_type || '未设'}${h.daily_calories ? ` · ${h.daily_calories}kcal` : ''}`
  }
  const b = g as BudgetPref
  return `工作日 ¥${b.weekday_daily_budget}/天`
}

function toForm(key: GroupKey, s: PreferenceSummary): Record<string, string> {
  const g = (s[key] || {}) as Record<string, unknown>
  const def = GROUPS.find((x) => x.key === key)!
  const out: Record<string, string> = {}
  for (const f of def.fields) {
    const v = g[f.name]
    out[f.name] = Array.isArray(v) ? v.join(', ') : v == null ? '' : String(v)
  }
  return out
}

export function ProfileDrawer({
  open,
  onClose,
  user,
  theme,
  onTheme,
}: {
  open: boolean
  onClose: () => void
  user: CurrentUser
  theme: 'auto' | 'light' | 'dark'
  onTheme: (t: 'auto' | 'light' | 'dark') => void
}) {
  const [summary, setSummary] = useState<PreferenceSummary | null>(null)
  const [editing, setEditing] = useState<GroupKey | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const { show, Toast } = useToast()

  useEffect(() => {
    if (!open) return
    getPreferenceSummary()
      .then(setSummary)
      .catch(() => show('偏好加载失败'))
  }, [open])

  const editingDef = useMemo(() => GROUPS.find((x) => x.key === editing), [editing])

  function openEditor(key: GroupKey) {
    if (!summary) return
    setForm(toForm(key, summary))
    setEditing(key)
  }

  async function saveEditor() {
    if (!editing) return
    const payload: Record<string, unknown> = {}
    for (const f of editingDef!.fields) {
      const raw = form[f.name] ?? ''
      if (f.type === 'list') {
        payload[f.name] = raw
          .split(/[,，]/)
          .map((s) => s.trim())
          .filter(Boolean)
      } else if (f.type === 'number') {
        payload[f.name] = raw === '' ? null : Number(raw)
      } else {
        payload[f.name] = raw
      }
    }
    try {
      await API_MAP[editing](payload)
      show('已保存')
      setEditing(null)
      const s = await getPreferenceSummary()
      setSummary(s)
    } catch {
      show('保存失败')
    }
  }

  return (
    <div className={'overlay' + (open ? ' open' : '')} aria-hidden={!open}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="我的">
        <div className="drawer-head">
          <div>
            <h2>我的</h2>
            <div className="card-sub">饭决会按这些偏好做决定</div>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            <CloseIcon />
          </button>
        </div>

        <div className="card">
          <div className="settings">
            {GROUPS.map((g) => (
              <button key={g.key} className="setting-row" onClick={() => openEditor(g.key)}>
                <span className="setting-icon">{g.icon}</span>
                <span className="setting-copy">
                  <b>{g.label}</b>
                  <span>{summary ? subtitleFor(g.key, summary) : '加载中…'}</span>
                </span>
                <span className="setting-value">编辑 ›</span>
              </button>
            ))}
          </div>
        </div>

        <div className="section-label">外观</div>
        <div className="card">
          <div className="card-title">跟随你的使用环境</div>
          <div className="card-sub">选择浅色 / 深色，或交给系统</div>
          <div className="theme-row">
            <button className={'theme-choice' + (theme === 'auto' ? ' active' : '')} onClick={() => onTheme('auto')}>
              自动
            </button>
            <button className={'theme-choice' + (theme === 'light' ? ' active' : '')} onClick={() => onTheme('light')}>
              明亮
            </button>
            <button className={'theme-choice' + (theme === 'dark' ? ' active' : '')} onClick={() => onTheme('dark')}>
              深色
            </button>
          </div>
        </div>

        <div className="card">
          <div className="card-title">已登录</div>
          <div className="pref-text">
            {user.name}（{user.role}）
          </div>
        </div>
      </aside>

      {editing && editingDef ? (
        <div className="modal-overlay open" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <h2>编辑{editingDef.label}</h2>
              <button className="icon-button" onClick={() => setEditing(null)} aria-label="关闭">
                <CloseIcon />
              </button>
            </div>
            {editingDef.fields.map((f) => (
              <div className="field" key={f.name}>
                <label>{f.label}</label>
                <input
                  value={form[f.name] ?? ''}
                  inputMode={f.type === 'number' ? 'decimal' : undefined}
                  onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
                />
              </div>
            ))}
            <div className="modal-actions">
              <button className="button" onClick={() => setEditing(null)}>
                取消
              </button>
              <button className="button primary" onClick={saveEditor}>
                保存
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {Toast}
    </div>
  )
}
