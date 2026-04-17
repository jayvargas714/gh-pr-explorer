import { create } from 'zustand'
import type {
  TimelineEvent,
  TimelineEventType,
  TimelineResponse,
} from '../api/types'
import { fetchTimeline } from '../api/timeline'

interface TimelineEntry {
  events: TimelineEvent[]
  prState: 'OPEN' | 'CLOSED' | 'MERGED'
  lastUpdated: string
  loading: boolean
  refreshing: boolean
  error: string | null
  expandedIds: Set<string>
  hiddenTypes: Set<TimelineEventType>
}

interface ModalTarget {
  owner: string
  repo: string
  prNumber: number
  title: string
  url: string
}

interface TimelineState {
  timelines: Record<string, TimelineEntry>
  openFor: ModalTarget | null

  open(target: ModalTarget): void
  close(): void
  load(
    owner: string,
    repo: string,
    prNumber: number,
    opts?: { force?: boolean }
  ): Promise<void>
  toggleExpanded(key: string, eventId: string): void
  toggleType(key: string, type: TimelineEventType): void
  resetFilters(key: string): void
}

function keyFor(owner: string, repo: string, prNumber: number): string {
  return `${owner}/${repo}/${prNumber}`
}

function emptyEntry(): TimelineEntry {
  return {
    events: [],
    prState: 'OPEN',
    lastUpdated: '',
    loading: false,
    refreshing: false,
    error: null,
    expandedIds: new Set(),
    hiddenTypes: new Set(),
  }
}

export const useTimelineStore = create<TimelineState>((set, get) => ({
  timelines: {},
  openFor: null,

  open(target) {
    const key = keyFor(target.owner, target.repo, target.prNumber)
    set((state) => ({
      openFor: target,
      timelines: state.timelines[key]
        ? state.timelines
        : { ...state.timelines, [key]: emptyEntry() },
    }))
    get().load(target.owner, target.repo, target.prNumber)
  },

  close() {
    set({ openFor: null })
  },

  async load(owner, repo, prNumber, opts = {}) {
    const key = keyFor(owner, repo, prNumber)
    const existing = get().timelines[key]
    const hasData = !!existing && existing.events.length > 0

    set((state) => ({
      timelines: {
        ...state.timelines,
        [key]: {
          ...(state.timelines[key] ?? emptyEntry()),
          loading: !hasData,
          refreshing: hasData,
          error: null,
        },
      },
    }))

    try {
      const resp: TimelineResponse = await fetchTimeline(owner, repo, prNumber, {
        refresh: opts.force,
      })
      set((state) => ({
        timelines: {
          ...state.timelines,
          [key]: {
            ...(state.timelines[key] ?? emptyEntry()),
            events: resp.events,
            prState: resp.pr_state,
            lastUpdated: resp.last_updated,
            loading: false,
            refreshing: resp.refreshing,
            error: null,
          },
        },
      }))
    } catch (err) {
      set((state) => ({
        timelines: {
          ...state.timelines,
          [key]: {
            ...(state.timelines[key] ?? emptyEntry()),
            loading: false,
            refreshing: false,
            error: err instanceof Error ? err.message : String(err),
          },
        },
      }))
    }
  },

  toggleExpanded(key, eventId) {
    set((state) => {
      const entry = state.timelines[key]
      if (!entry) return state
      const expandedIds = new Set(entry.expandedIds)
      if (expandedIds.has(eventId)) expandedIds.delete(eventId)
      else expandedIds.add(eventId)
      return {
        timelines: { ...state.timelines, [key]: { ...entry, expandedIds } },
      }
    })
  },

  toggleType(key, type) {
    set((state) => {
      const entry = state.timelines[key]
      if (!entry) return state
      const hiddenTypes = new Set(entry.hiddenTypes)
      if (hiddenTypes.has(type)) hiddenTypes.delete(type)
      else hiddenTypes.add(type)
      return {
        timelines: { ...state.timelines, [key]: { ...entry, hiddenTypes } },
      }
    })
  },

  resetFilters(key) {
    set((state) => {
      const entry = state.timelines[key]
      if (!entry) return state
      return {
        timelines: {
          ...state.timelines,
          [key]: { ...entry, hiddenTypes: new Set() },
        },
      }
    })
  },
}))

export function timelineKey(
  owner: string,
  repo: string,
  prNumber: number
): string {
  return keyFor(owner, repo, prNumber)
}
