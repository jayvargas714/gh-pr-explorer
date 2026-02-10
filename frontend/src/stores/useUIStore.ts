import { create } from 'zustand'

interface UIState {
  // Theme
  darkMode: boolean
  toggleTheme: () => void

  // Active views
  activeView: 'prs' | 'analytics' | 'workflows'
  setActiveView: (view: 'prs' | 'analytics' | 'workflows') => void

  activeAnalyticsTab: 'stats' | 'lifecycle' | 'activity' | 'responsiveness' | 'contributors'
  setActiveAnalyticsTab: (tab: 'stats' | 'lifecycle' | 'activity' | 'responsiveness' | 'contributors') => void

  // Panel visibility
  showQueuePanel: boolean
  setShowQueuePanel: (show: boolean) => void
  toggleQueuePanel: () => void

  showHistoryPanel: boolean
  setShowHistoryPanel: (show: boolean) => void
  toggleHistoryPanel: () => void

  // Global loading/error
  globalLoading: boolean
  setGlobalLoading: (loading: boolean) => void

  globalError: string | null
  setGlobalError: (error: string | null) => void
}

export const useUIStore = create<UIState>((set) => ({
  // Theme
  darkMode: true,
  toggleTheme: () =>
    set((state) => {
      const newDarkMode = !state.darkMode
      localStorage.setItem('theme', newDarkMode ? 'dark' : 'light')
      document.documentElement.classList.toggle('matrix-light', !newDarkMode)
      return { darkMode: newDarkMode }
    }),

  // Active views
  activeView: 'prs',
  setActiveView: (view) => set({ activeView: view }),

  activeAnalyticsTab: 'stats',
  setActiveAnalyticsTab: (tab) => set({ activeAnalyticsTab: tab }),

  // Panel visibility
  showQueuePanel: false,
  setShowQueuePanel: (show) => set({ showQueuePanel: show }),
  toggleQueuePanel: () => set((state) => ({ showQueuePanel: !state.showQueuePanel })),

  showHistoryPanel: false,
  setShowHistoryPanel: (show) => set({ showHistoryPanel: show }),
  toggleHistoryPanel: () => set((state) => ({ showHistoryPanel: !state.showHistoryPanel })),

  // Global loading/error
  globalLoading: false,
  setGlobalLoading: (loading) => set({ globalLoading: loading }),

  globalError: null,
  setGlobalError: (error) => set({ globalError: error }),
}))
