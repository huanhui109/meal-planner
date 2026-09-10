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

  fetchSummary: async () => {
    set({ loading: true })
    try {
      const summary = await preferencesApi.getPreferenceSummary()
      set({ summary: summary ?? EMPTY_SUMMARY, loaded: true })
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
