import { create } from 'zustand'
import { setSetting } from '../api/settings'

interface FilterState {
  // Basic filters
  state: string
  author: string
  assignee: string
  labels: string[]
  base: string
  head: string
  draft: string
  noAssignee: boolean
  noLabel: boolean
  milestone: string
  linked: string

  // Review filters
  review: string[]
  reviewedBy: string
  reviewRequested: string
  status: string[]

  // People filters
  involves: string
  mentions: string
  commenter: string

  // Date filters
  createdAfter: string
  createdBefore: string
  updatedAfter: string
  updatedBefore: string
  mergedAfter: string
  mergedBefore: string
  closedAfter: string
  closedBefore: string

  // Advanced filters
  search: string
  searchIn: string[]
  comments: string
  reactions: string
  interactions: string
  teamReviewRequested: string
  excludeLabels: string[]
  excludeAuthor: string
  excludeMilestone: string
  sortBy: string
  sortDirection: string
  limit: number

  // Persistence
  _skipSave: boolean

  // Actions
  setFilter: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void
  resetFilters: () => void
  getActiveFiltersCount: () => number
  restoreFilters: (saved: Record<string, any>) => void
}

const DEFAULT_FILTERS: Omit<FilterState, 'setFilter' | 'resetFilters' | 'getActiveFiltersCount' | 'restoreFilters' | '_skipSave'> = {
  state: 'open',
  author: '',
  assignee: '',
  labels: [],
  base: '',
  head: '',
  draft: '',
  noAssignee: false,
  noLabel: false,
  milestone: '',
  linked: '',
  review: [],
  reviewedBy: '',
  reviewRequested: '',
  status: [],
  involves: '',
  mentions: '',
  commenter: '',
  createdAfter: '',
  createdBefore: '',
  updatedAfter: '',
  updatedBefore: '',
  mergedAfter: '',
  mergedBefore: '',
  closedAfter: '',
  closedBefore: '',
  search: '',
  searchIn: [],
  comments: '',
  reactions: '',
  interactions: '',
  teamReviewRequested: '',
  excludeLabels: [],
  excludeAuthor: '',
  excludeMilestone: '',
  sortBy: '',
  sortDirection: 'desc',
  limit: 100,
}

// Debounced save to backend
let saveTimeout: ReturnType<typeof setTimeout> | null = null

export function debouncedSaveSettings(filters: Record<string, any>, accountLogin: string | null, repoFullName: string | null) {
  if (saveTimeout) clearTimeout(saveTimeout)
  saveTimeout = setTimeout(() => {
    setSetting('filter_settings', {
      filters,
      selectedAccountLogin: accountLogin,
      selectedRepoFullName: repoFullName,
    }).catch((err) => console.error('Failed to save settings:', err))
  }, 1000)
}

export const useFilterStore = create<FilterState>((set, get) => ({
  ...DEFAULT_FILTERS,
  _skipSave: false,

  setFilter: (key, value) => set({ [key]: value }),

  resetFilters: () => set(DEFAULT_FILTERS),

  restoreFilters: (saved: Record<string, any>) => {
    const updates: Record<string, any> = { _skipSave: true }
    const state = get()
    for (const key of Object.keys(saved)) {
      if (key in state && key !== 'setFilter' && key !== 'resetFilters' && key !== 'getActiveFiltersCount' && key !== 'restoreFilters' && key !== '_skipSave') {
        updates[key] = saved[key]
      }
    }
    set(updates)
    // Re-enable saving after restore
    setTimeout(() => set({ _skipSave: false }), 100)
  },

  getActiveFiltersCount: () => {
    const state = get()
    let count = 0

    if (state.state !== 'open') count++
    if (state.author) count++
    if (state.assignee) count++
    if (state.labels.length > 0) count++
    if (state.base) count++
    if (state.head) count++
    if (state.draft) count++
    if (state.noAssignee) count++
    if (state.noLabel) count++
    if (state.milestone) count++
    if (state.linked) count++
    if (state.review.length > 0) count++
    if (state.reviewedBy) count++
    if (state.reviewRequested) count++
    if (state.status.length > 0) count++
    if (state.involves) count++
    if (state.mentions) count++
    if (state.commenter) count++
    if (state.createdAfter) count++
    if (state.createdBefore) count++
    if (state.updatedAfter) count++
    if (state.updatedBefore) count++
    if (state.mergedAfter) count++
    if (state.mergedBefore) count++
    if (state.closedAfter) count++
    if (state.closedBefore) count++
    if (state.search) count++
    if (state.searchIn.length > 0) count++
    if (state.comments) count++
    if (state.reactions) count++
    if (state.interactions) count++
    if (state.teamReviewRequested) count++
    if (state.excludeLabels.length > 0) count++
    if (state.excludeAuthor) count++
    if (state.excludeMilestone) count++
    if (state.sortBy) count++
    if (state.limit !== 100) count++

    return count
  },
}))
