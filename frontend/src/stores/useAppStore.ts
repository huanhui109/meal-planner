import { create } from 'zustand'

interface AppState {
  loading: boolean
  setLoading: (loading: boolean) => void
}

export const useAppStore = create<AppState>((set) => ({
  loading: false,
  setLoading: (loading) => set({ loading }),
}))
