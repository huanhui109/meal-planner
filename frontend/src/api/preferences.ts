import apiClient, { unwrap } from './client'
import type {
  AllergyRestriction,
  Budget,
  DietPreference,
  HealthGoal,
  Household,
  UserPreferenceSummary,
} from '../types'

export const updateHousehold = (data: Partial<Household>) =>
  unwrap<Household>(apiClient.put('/preferences/household', data))

export const updateDiet = (data: Partial<DietPreference>) =>
  unwrap<DietPreference>(apiClient.put('/preferences/diet', data))

export const updateAllergy = (data: Partial<AllergyRestriction>) =>
  unwrap<AllergyRestriction>(apiClient.put('/preferences/allergy', data))

export const updateHealthGoal = (data: Partial<HealthGoal>) =>
  unwrap<HealthGoal>(apiClient.put('/preferences/health-goal', data))

export const updateBudget = (data: Partial<Budget>) =>
  unwrap<Budget>(apiClient.put('/preferences/budget', data))

/** 一次性拿到全部偏好 (未配置的项为 null) */
export const getPreferenceSummary = () =>
  unwrap<UserPreferenceSummary>(apiClient.get('/preferences/summary'))
