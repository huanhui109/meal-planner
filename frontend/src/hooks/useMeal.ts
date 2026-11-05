import { useCallback, useEffect, useRef, useState } from 'react'
import type { MealContext, MealSlotName, MealView } from '@shared/meal'
import { actOnMeal, getCurrentMeal, proposeMeal, recordMealView } from '../api/meals'

const conflict = (error: unknown) => (error as { status?: number }).status === 409

export function useMeal(slot?: MealSlotName, date?: string) {
  const [view, setView] = useState<MealView | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const current = useRef(view)
  current.current = view
  const working = useRef<number | null>(null)
  const generation = useRef(0)
  const hasLoaded = useRef(false)

  const refresh = useCallback(async (automatic = false) => {
    if (working.current) return
    const request = ++generation.current
    const shouldPropose = automatic || !hasLoaded.current
    try {
      let next = await getCurrentMeal(slot, date)
      if (request !== generation.current) return
      hasLoaded.current = true
      setView(next)
      if (shouldPropose && !next.proposal) {
        working.current = request
        setBusy(true)
        try {
          next = await proposeMeal(next.context, next.revision)
        } catch (err) {
          if (!conflict(err)) throw err
          next = await getCurrentMeal(slot, date)
        } finally {
          if (working.current === request) working.current = null
          if (request === generation.current) setBusy(false)
        }
      }
      if (request === generation.current) {
        setView(next)
        setError('')
      }
    } catch (err) {
      if (request === generation.current) setError((err as Error).message)
    } finally {
      if (request === generation.current) setLoading(false)
    }
  }, [slot, date])

  useEffect(() => {
    working.current = null
    hasLoaded.current = false
    setBusy(false)
    setLoading(true)
    setView(null)
    setError('')
    void refresh(true)
    return () => { generation.current += 1 }
  }, [refresh])

  useEffect(() => {
    const update = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    const timer = window.setInterval(update, 15000)
    window.addEventListener('focus', update)
    document.addEventListener('visibilitychange', update)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', update)
      document.removeEventListener('visibilitychange', update)
    }
  }, [refresh])

  const viewed = view?.proposal?.id
  useEffect(() => {
    const record = () => {
      if (viewed && document.visibilityState === 'visible') void recordMealView(viewed).catch(() => undefined)
    }
    record()
    document.addEventListener('visibilitychange', record)
    return () => document.removeEventListener('visibilitychange', record)
  }, [viewed])

  const mutate = async (operation: (latest: MealView) => Promise<MealView>) => {
    if (working.current || !current.current) return false
    const request = ++generation.current
    working.current = request
    setBusy(true)
    setError('')
    try {
      const next = await operation(current.current)
      if (request === generation.current) setView(next)
      return true
    } catch (err) {
      if (request === generation.current) {
        setError((err as Error).message)
        if (conflict(err)) {
          try {
            const next = await getCurrentMeal(slot, date)
            if (request === generation.current) setView(next)
          } catch { /* Keep the existing view and explicit error on network failure. */ }
        }
      }
      return false
    } finally {
      if (working.current === request) working.current = null
      if (request === generation.current) setBusy(false)
    }
  }

  return {
    view, loading, busy, error, refresh,
    propose: (changes: Partial<MealContext> = {}) => mutate(
      (latest) => proposeMeal({ ...latest.context, ...changes }, latest.revision),
    ),
    act: (action: 'accept' | 'complete' | 'undo', deduct = false) => mutate(
      (latest) => actOnMeal(latest.proposal!.id, action, latest.revision, deduct),
    ),
  }
}
