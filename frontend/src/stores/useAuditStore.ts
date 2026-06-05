import { create } from 'zustand'
import {
  fetchActiveAudits,
  startAudit as apiStartAudit,
  cancelAudit as apiCancelAudit,
} from '../api/audits'
import type { ActiveAudit } from '../api/types'

interface AuditStartArgs {
  number: number
  url: string
  owner: string
  repo: string
  title?: string
  author?: string
  head_ref?: string
  base_ref?: string
}

interface AuditStoreState {
  activeAudits: ActiveAudit[]
  startAudit: (args: AuditStartArgs) => Promise<void>
  cancelAudit: (owner: string, repo: string, prNumber: number) => Promise<void>
  refreshActiveAudits: () => Promise<void>
  /** Status string if an audit is running/recent for this PR, else null. */
  auditStatusFor: (owner: string, repo: string, prNumber: number) => string | null
}

export const useAuditStore = create<AuditStoreState>((set, get) => ({
  activeAudits: [],

  startAudit: async (args) => {
    await apiStartAudit(args)
    await get().refreshActiveAudits()
  },

  cancelAudit: async (owner, repo, prNumber) => {
    await apiCancelAudit(owner, repo, prNumber)
    await get().refreshActiveAudits()
  },

  refreshActiveAudits: async () => {
    try {
      const resp = await fetchActiveAudits()
      set({ activeAudits: resp.audits })
    } catch {
      // transient; leave prior state
    }
  },

  auditStatusFor: (owner, repo, prNumber) => {
    const key = `${owner}/${repo}/${prNumber}`
    const found = get().activeAudits.find((a) => a.key === key)
    return found ? found.status : null
  },
}))
