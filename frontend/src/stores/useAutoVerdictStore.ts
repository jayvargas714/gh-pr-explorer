import { create } from 'zustand'
import { getAutoVerdictConfig, saveAutoVerdictConfig } from '../api/autoVerdict'
import { AutoVerdictConfig } from '../api/types'

/** Mirrors DEFAULT_CRITERIA in backend/services/auto_verdict_config.py. */
export const DEFAULT_AUTO_VERDICT_CONFIG: AutoVerdictConfig = {
  enabled: false,
  maxCritical: 0,
  maxMajor: 0,
  maxMinor: 99,
  allowAutoApprove: false,
  autoFollowupReview: false,
  mediationDisputedThreshold: 3,
}

interface AutoVerdictState {
  config: AutoVerdictConfig
  loading: boolean
  saving: boolean
  error: string | null
  loaded: boolean
  load: () => Promise<void>
  save: (config: AutoVerdictConfig) => Promise<boolean>
}

export const useAutoVerdictStore = create<AutoVerdictState>((set) => ({
  config: DEFAULT_AUTO_VERDICT_CONFIG,
  loading: false,
  saving: false,
  error: null,
  loaded: false,

  load: async () => {
    set({ loading: true, error: null })
    try {
      const { config } = await getAutoVerdictConfig()
      set({ config, loading: false, loaded: true })
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load auto-verdict config',
      })
    }
  },

  save: async (config) => {
    set({ saving: true, error: null })
    try {
      const saved = await saveAutoVerdictConfig(config)
      set({ config: saved.config, saving: false, loaded: true })
      return true
    } catch (err) {
      set({
        saving: false,
        error: err instanceof Error ? err.message : 'Failed to save auto-verdict config',
      })
      return false
    }
  },
}))

/** Human-readable threshold summary, used in card tooltips. */
export function describeCriteria(config: AutoVerdictConfig): string {
  const limits = `max ${config.maxCritical} critical / ${config.maxMajor} major / ${config.maxMinor} minor`
  const approve = config.allowAutoApprove ? 'auto-approve on' : 'auto-approve off'
  const mediation = `mediation at ${config.mediationDisputedThreshold} disputed`
  return config.enabled ? `${limits} — ${approve} — ${mediation}` : 'Auto verdicts globally disabled'
}
