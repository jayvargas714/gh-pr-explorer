import { create } from 'zustand'
import { Milestone, Team } from '../api/types'
import { fetchRepoMetadata } from '../api/repos'

interface MetadataState {
  contributors: string[]
  labels: string[]
  branches: string[]
  milestones: Milestone[]
  teams: Team[]
  loading: boolean
  error: string | null

  loadMetadata: (owner: string, repo: string) => Promise<void>
  clear: () => void
}

export const useMetadataStore = create<MetadataState>((set) => ({
  contributors: [],
  labels: [],
  branches: [],
  milestones: [],
  teams: [],
  loading: false,
  error: null,

  loadMetadata: async (owner: string, repo: string) => {
    set({ loading: true, error: null })
    try {
      const data = await fetchRepoMetadata(owner, repo)
      set({
        contributors: data.contributors,
        labels: data.labels,
        branches: data.branches,
        milestones: data.milestones,
        teams: data.teams,
        loading: false,
      })
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to load metadata',
        loading: false,
      })
    }
  },

  clear: () =>
    set({
      contributors: [],
      labels: [],
      branches: [],
      milestones: [],
      teams: [],
      loading: false,
      error: null,
    }),
}))
