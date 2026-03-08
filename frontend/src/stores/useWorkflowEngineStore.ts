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
    set({ loading: true, error: null })
    try {
      const instances = await listInstances(repo)
      set({ instances, loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  fetchInstance: async (id: number) => {
    set({ loading: true, error: null })
    try {
      const instance = await getInstance(id)
      set({ selectedInstance: instance, loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
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
    set({ loading: true, error: null })
    try {
      const result = await runWorkflow({ template_id: templateId, repo, config })
      await get().fetchInstances()
      set({ loading: false })
      return result.id
    } catch (e) {
      set({ error: String(e), loading: false })
      return null
    }
  },

  approveGate: async (instanceId: number, data?: Record<string, unknown>) => {
    set({ loading: true, error: null })
    try {
      await gateAction(instanceId, 'approve', data)
      await get().fetchInstance(instanceId)
      set({ loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  rejectGate: async (instanceId: number, data?: Record<string, unknown>) => {
    set({ loading: true, error: null })
    try {
      await gateAction(instanceId, 'reject', data)
      await get().fetchInstance(instanceId)
      set({ loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  reviseGate: async (instanceId: number, feedback: string) => {
    set({ loading: true, error: null })
    try {
      await gateAction(instanceId, 'revise', { feedback })
      await get().fetchInstance(instanceId)
      set({ loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
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
