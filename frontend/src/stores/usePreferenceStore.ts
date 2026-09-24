import { create } from 'zustand'
import * as preferencesApi from '../api/preferences'
import type {
  AllergyRestriction,
  Budget,
  DietPreference,
  HealthGoal,
  Household,
  UserPreferenceSummary,
} from '../types'

interface PreferenceState {
  loading: boolean
  loaded: boolean
  summary: UserPreferenceSummary | null
  /**
   * 每次**从服务端重新拉取**就 +1。
   *
   * 偏好页 5 张表单是同时挂载的, 如果表单靠 `summary` 的引用变化来同步初始值,
   * 那么保存任意一张卡 (update* 会 set 一个新的 summary 对象) 会把另外 4 张
   * 正在编辑、还没保存的表单一起重置成服务端值 —— 用户填的东西静默消失。
   * 所以同步只认 syncToken, 而 update* 不动它。
   */
  syncToken: number
  fetchSummary: () => Promise<void>
  updateHousehold: (data: Partial<Household>) => Promise<void>
  updateDiet: (data: Partial<DietPreference>) => Promise<void>
  updateAllergy: (data: Partial<AllergyRestriction>) => Promise<void>
  updateHealthGoal: (data: Partial<HealthGoal>) => Promise<void>
  updateBudget: (data: Partial<Budget>) => Promise<void>
}

const EMPTY_SUMMARY: UserPreferenceSummary = {
  household: null,
  diet_preference: null,
  allergy_restriction: null,
  health_goal: null,
  budget: null,
}

export const usePreferenceStore = create<PreferenceState>((set, get) => ({
  loading: false,
  loaded: false,
  summary: null,
  syncToken: 0,

  fetchSummary: async () => {
    set({ loading: true })
    try {
      const summary = await preferencesApi.getPreferenceSummary()
      set((state) => ({
        summary: summary ?? EMPTY_SUMMARY,
        loaded: true,
        syncToken: state.syncToken + 1,
      }))
    } finally {
      set({ loading: false })
    }
  },

  updateHousehold: async (data) => {
    const result = await preferencesApi.updateHousehold(data)
    set({ summary: { ...(get().summary ?? EMPTY_SUMMARY), household: result } })
  },

  updateDiet: async (data) => {
    const result = await preferencesApi.updateDiet(data)
    set({ summary: { ...(get().summary ?? EMPTY_SUMMARY), diet_preference: result } })
  },

  updateAllergy: async (data) => {
    const result = await preferencesApi.updateAllergy(data)
    set({ summary: { ...(get().summary ?? EMPTY_SUMMARY), allergy_restriction: result } })
  },

  updateHealthGoal: async (data) => {
    const result = await preferencesApi.updateHealthGoal(data)
    set({ summary: { ...(get().summary ?? EMPTY_SUMMARY), health_goal: result } })
  },

  updateBudget: async (data) => {
    const result = await preferencesApi.updateBudget(data)
    set({ summary: { ...(get().summary ?? EMPTY_SUMMARY), budget: result } })
  },
}))
