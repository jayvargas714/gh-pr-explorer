import { create } from 'zustand'
import {
  createReviewer,
  deleteReviewer,
  getAutomationConfig,
  listReviewers,
  saveAutomationConfig,
  updateReviewer,
} from '../api/automation'
import { AutomationConfig, ReviewerInfo } from '../api/types'

/** Mirrors DEFAULT_CONFIG in backend/services/automation_config.py. */
export const DEFAULT_AUTOMATION_CONFIG: AutomationConfig = {
  scope: 'off',
  authors: [],
  repoAllowlist: [],
  maxConcurrentAutoReviews: 2,
  ignorePatterns: [],
  defaultRule: { reviewerKey: 'default', autoVerdict: false, autoVerdictMode: 'verdict' },
  rules: [],
}

/** Fallback so reviewer pickers render before the registry loads. */
export const FALLBACK_REVIEWERS: ReviewerInfo[] = [
  { key: 'default', label: 'Default Reviewer', agentName: 'elite-code-reviewer', promptContext: null, isBuiltin: true },
  { key: 'pb', label: 'PB Reviewer', agentName: 'product-brief-reviewer', promptContext: null, isBuiltin: true },
  { key: 'ed', label: 'ED Reviewer', agentName: 'ed-reviewer', promptContext: null, isBuiltin: true },
]

interface AutomationState {
  config: AutomationConfig
  reviewers: ReviewerInfo[]
  loading: boolean
  saving: boolean
  error: string | null
  loaded: boolean
  load: () => Promise<void>
  saveConfig: (config: AutomationConfig) => Promise<boolean>
  addReviewer: (reviewer: { key: string; label: string; agentName: string; promptContext?: string | null }) => Promise<boolean>
  editReviewer: (key: string, updates: { label?: string; agentName?: string; promptContext?: string | null }) => Promise<boolean>
  removeReviewer: (key: string) => Promise<boolean>
}

export const useAutomationStore = create<AutomationState>((set, get) => ({
  config: DEFAULT_AUTOMATION_CONFIG,
  reviewers: FALLBACK_REVIEWERS,
  loading: false,
  saving: false,
  error: null,
  loaded: false,

  load: async () => {
    set({ loading: true, error: null })
    try {
      const [{ config }, { reviewers }] = await Promise.all([
        getAutomationConfig(),
        listReviewers(),
      ])
      set({ config, reviewers, loading: false, loaded: true })
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load automation config',
      })
    }
  },

  saveConfig: async (config) => {
    set({ saving: true, error: null })
    try {
      const saved = await saveAutomationConfig(config)
      set({ config: saved.config, saving: false, loaded: true })
      return true
    } catch (err) {
      set({
        saving: false,
        error: err instanceof Error ? err.message : 'Failed to save automation config',
      })
      return false
    }
  },

  addReviewer: async (reviewer) => {
    set({ saving: true, error: null })
    try {
      await createReviewer(reviewer)
      const { reviewers } = await listReviewers()
      set({ reviewers, saving: false })
      return true
    } catch (err) {
      set({ saving: false, error: err instanceof Error ? err.message : 'Failed to create reviewer' })
      return false
    }
  },

  editReviewer: async (key, updates) => {
    set({ saving: true, error: null })
    try {
      await updateReviewer(key, updates)
      const { reviewers } = await listReviewers()
      set({ reviewers, saving: false })
      return true
    } catch (err) {
      set({ saving: false, error: err instanceof Error ? err.message : 'Failed to update reviewer' })
      return false
    }
  },

  removeReviewer: async (key) => {
    const referenced =
      get().config.defaultRule.reviewerKey === key ||
      get().config.rules.some((rule) => rule.reviewerKey === key)
    if (referenced) {
      set({ error: `Reviewer '${key}' is referenced by a routing rule — update the rules first` })
      return false
    }
    set({ saving: true, error: null })
    try {
      await deleteReviewer(key)
      const { reviewers } = await listReviewers()
      set({ reviewers, saving: false })
      return true
    } catch (err) {
      set({ saving: false, error: err instanceof Error ? err.message : 'Failed to delete reviewer' })
      return false
    }
  },
}))
