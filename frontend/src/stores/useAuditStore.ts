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

interface AuditErrorModalState {
  show: boolean
  prNumber: number | null
  prTitle: string
  prUrl: string
  owner: string
  repo: string
  errorOutput: string
  exitCode: number | null
}

interface AuditStoreState {
  activeAudits: ActiveAudit[]
  /** Audit error modal (mirrors the review error modal). */
  auditErrorModal: AuditErrorModalState
  startAudit: (args: AuditStartArgs) => Promise<void>
  cancelAudit: (owner: string, repo: string, prNumber: number) => Promise<void>
  refreshActiveAudits: () => Promise<void>
  /** Status string if an audit is running/recent for this PR, else null. */
  auditStatusFor: (owner: string, repo: string, prNumber: number) => string | null
  /** Full active audit record for this PR (reacts to activeAudits), else null. */
  activeAuditFor: (owner: string, repo: string, prNumber: number) => ActiveAudit | null
  showAuditError: (
    prNumber: number,
    prTitle: string,
    prUrl: string,
    owner: string,
    repo: string,
    errorOutput: string,
    exitCode: number | null,
  ) => void
  hideAuditError: () => void
}

const EMPTY_AUDIT_ERROR_MODAL: AuditErrorModalState = {
  show: false,
  prNumber: null,
  prTitle: '',
  prUrl: '',
  owner: '',
  repo: '',
  errorOutput: '',
  exitCode: null,
}

export const useAuditStore = create<AuditStoreState>((set, get) => ({
  activeAudits: [],
  auditErrorModal: EMPTY_AUDIT_ERROR_MODAL,

  startAudit: async (args) => {
    const key = `${args.owner}/${args.repo}/${args.number}`
    // Optimistically mark the audit as running so the UI reflects it immediately,
    // before the API round-trip. refreshActiveAudits() reconciles from the server.
    const optimistic: ActiveAudit = {
      key,
      owner: args.owner,
      repo: args.repo,
      pr_number: args.number,
      status: 'running',
      started_at: new Date().toISOString(),
      completed_at: '',
      pr_url: args.url,
      audit_file: '',
      exit_code: null,
      error_output: '',
    }
    set((state) => ({
      activeAudits: [
        ...state.activeAudits.filter((a) => a.key !== key),
        optimistic,
      ],
    }))
    try {
      await apiStartAudit(args)
    } catch (err) {
      // Roll back the optimistic entry on failure so the picker is usable again.
      set((state) => ({
        activeAudits: state.activeAudits.filter((a) => a.key !== key),
      }))
      throw err
    }
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

  activeAuditFor: (owner, repo, prNumber) => {
    const key = `${owner}/${repo}/${prNumber}`
    return get().activeAudits.find((a) => a.key === key) ?? null
  },

  showAuditError: (prNumber, prTitle, prUrl, owner, repo, errorOutput, exitCode) =>
    set({
      auditErrorModal: {
        show: true,
        prNumber,
        prTitle,
        prUrl,
        owner,
        repo,
        errorOutput,
        exitCode,
      },
    }),

  hideAuditError: () => set({ auditErrorModal: EMPTY_AUDIT_ERROR_MODAL }),
}))
