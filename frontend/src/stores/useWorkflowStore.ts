import { create } from 'zustand'
import { WorkflowRun, WorkflowStats, Workflow } from '../api/types'

interface WorkflowState {
  // Workflows
  workflowRuns: WorkflowRun[]
  workflowStats: WorkflowStats | null
  workflows: Workflow[]
  loading: boolean
  error: string | null

  // Filters
  workflowFilter: string
  branchFilter: string
  eventFilter: string
  conclusionFilter: string

  // Sorting & Pagination
  sortBy: string
  sortDirection: 'asc' | 'desc'
  currentPage: number
  workflowsPerPage: number

  // Actions
  setWorkflowRuns: (runs: WorkflowRun[]) => void
  setWorkflowStats: (stats: WorkflowStats | null) => void
  setWorkflows: (workflows: Workflow[]) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void

  setWorkflowFilter: (filter: string) => void
  setBranchFilter: (filter: string) => void
  setEventFilter: (filter: string) => void
  setConclusionFilter: (filter: string) => void
  resetFilters: () => void

  sortWorkflows: (column: string) => void
  setCurrentPage: (page: number) => void

  // Computed
  getSortedWorkflows: () => WorkflowRun[]
  getPaginatedWorkflows: () => WorkflowRun[]
  getTotalPages: () => number
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  // Workflows
  workflowRuns: [],
  workflowStats: null,
  workflows: [],
  loading: false,
  error: null,

  // Filters
  workflowFilter: '',
  branchFilter: '',
  eventFilter: '',
  conclusionFilter: '',

  // Sorting & Pagination
  sortBy: 'created_at',
  sortDirection: 'desc',
  currentPage: 1,
  workflowsPerPage: 25,

  // Actions
  setWorkflowRuns: (runs) => set({ workflowRuns: runs, currentPage: 1 }),
  setWorkflowStats: (stats) => set({ workflowStats: stats }),
  setWorkflows: (workflows) => set({ workflows }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  setWorkflowFilter: (filter) => set({ workflowFilter: filter }),
  setBranchFilter: (filter) => set({ branchFilter: filter }),
  setEventFilter: (filter) => set({ eventFilter: filter }),
  setConclusionFilter: (filter) => set({ conclusionFilter: filter }),
  resetFilters: () =>
    set({
      workflowFilter: '',
      branchFilter: '',
      eventFilter: '',
      conclusionFilter: '',
    }),

  sortWorkflows: (column) =>
    set((state) => ({
      sortBy: column,
      sortDirection:
        state.sortBy === column && state.sortDirection === 'desc' ? 'asc' : 'desc',
    })),

  setCurrentPage: (page) => set({ currentPage: page }),

  // Computed
  getSortedWorkflows: () => {
    const { workflowRuns, sortBy, sortDirection } = get()
    if (!sortBy) return workflowRuns

    return [...workflowRuns].sort((a, b) => {
      const aVal = (a as any)[sortBy]
      const bVal = (b as any)[sortBy]

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal
      }
      return sortDirection === 'asc'
        ? String(aVal).localeCompare(String(bVal))
        : String(bVal).localeCompare(String(aVal))
    })
  },

  getPaginatedWorkflows: () => {
    const { currentPage, workflowsPerPage } = get()
    const sorted = get().getSortedWorkflows()
    const startIndex = (currentPage - 1) * workflowsPerPage
    const endIndex = startIndex + workflowsPerPage
    return sorted.slice(startIndex, endIndex)
  },

  getTotalPages: () => {
    const { workflowsPerPage } = get()
    const sorted = get().getSortedWorkflows()
    return Math.ceil(sorted.length / workflowsPerPage)
  },
}))
