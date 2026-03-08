import { create } from 'zustand'
import {
  WorkflowTemplate,
  WorkflowInstance,
  Agent,
  listTemplates,
  listInstances,
  getInstance,
  listAgents,
  runWorkflow,
  gateAction,
  cancelInstance,
} from '../api/workflow-engine'

interface WorkflowEngineState {
  templates: WorkflowTemplate[]
  instances: WorkflowInstance[]
  agents: Agent[]
  selectedInstance: WorkflowInstance | null
  loading: boolean
  loadingInstances: boolean
  loadingInstance: boolean
  submitting: boolean
  error: string | null

  fetchTemplates: () => Promise<void>
  fetchInstances: (repo?: string) => Promise<void>
  fetchInstance: (id: number) => Promise<void>
  fetchAgents: () => Promise<void>
  startRun: (templateId: number, repo: string, config?: Record<string, unknown>) => Promise<number | null>
  approveGate: (instanceId: number, data?: Record<string, unknown>) => Promise<void>
  rejectGate: (instanceId: number, data?: Record<string, unknown>) => Promise<void>
  reviseGate: (instanceId: number, feedback: string) => Promise<void>
  cancelRun: (instanceId: number) => Promise<void>
  clearError: () => void
}

export const useWorkflowEngineStore = create<WorkflowEngineState>((set, get) => ({
  templates: [],
  instances: [],
  agents: [],
  selectedInstance: null,
  loading: false,
  loadingInstances: false,
  loadingInstance: false,
  submitting: false,
  error: null,

  fetchTemplates: async () => {
    set({ loading: true, error: null })
    try {
      const templates = await listTemplates()
      set({ templates, loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  fetchInstances: async (repo?: string) => {
    set({ loadingInstances: true })
    try {
      const instances = await listInstances(repo)
      set({ instances, loadingInstances: false })
    } catch (e) {
      set({ error: String(e), loadingInstances: false })
    }
  },

  fetchInstance: async (id: number) => {
    set({ loadingInstance: true })
    try {
      const instance = await getInstance(id)
      set({ selectedInstance: instance, loadingInstance: false })
    } catch (e) {
      set({ error: String(e), loadingInstance: false })
    }
  },

  fetchAgents: async () => {
    try {
      const agents = await listAgents()
      set({ agents })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  startRun: async (templateId: number, repo: string, config?: Record<string, unknown>) => {
    set({ submitting: true, error: null })
    try {
      const result = await runWorkflow({ template_id: templateId, repo, config })
      await get().fetchInstances()
      set({ submitting: false })
      return result.id
    } catch (e) {
      set({ error: String(e), submitting: false })
      return null
    }
  },

  approveGate: async (instanceId: number, data?: Record<string, unknown>) => {
    set({ submitting: true, error: null })
    try {
      await gateAction(instanceId, 'approve', data)
      await get().fetchInstance(instanceId)
      set({ submitting: false })
    } catch (e) {
      set({ error: String(e), submitting: false })
    }
  },

  rejectGate: async (instanceId: number, data?: Record<string, unknown>) => {
    set({ submitting: true, error: null })
    try {
      await gateAction(instanceId, 'reject', data)
      await get().fetchInstance(instanceId)
      set({ submitting: false })
    } catch (e) {
      set({ error: String(e), submitting: false })
    }
  },

  reviseGate: async (instanceId: number, feedback: string) => {
    set({ submitting: true, error: null })
    try {
      await gateAction(instanceId, 'revise', { feedback })
      await get().fetchInstance(instanceId)
      set({ submitting: false })
    } catch (e) {
      set({ error: String(e), submitting: false })
    }
  },

  cancelRun: async (instanceId: number) => {
    try {
      await cancelInstance(instanceId)
      await get().fetchInstances()
      if (get().selectedInstance?.id === instanceId) {
        await get().fetchInstance(instanceId)
      }
    } catch (e) {
      set({ error: String(e) })
    }
  },

  clearError: () => set({ error: null }),
}))
