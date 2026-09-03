import { create } from 'zustand'
import {
  AutoVerdictCriteriaOverride,
  AutoVerdictMode,
  AutoVerdictReviewer,
  AutomationDispatchState,
  PipelineRow,
  PipelineStage,
} from '../api/types'
import { fetchPipeline } from '../api/pipeline'
import { enrollAutomationDispatch, optOutAutomationDispatch } from '../api/automation'
import { setCardAutoVerdict } from '../api/autoVerdict'
import { addToQueue, fetchMergeQueue } from '../api/queue'
import { useQueueStore } from './useQueueStore'
import { BadgeFilterKey, BadgeFilterMode } from '../utils/badgeFilters'
import { PipelineSort, PipelineSortColumn, prUrl } from '../components/pipeline/pipelineFilters'

export type BulkAction = 'optout' | 'enroll' | 'arm' | 'disarm' | 'watch'

export interface BulkProgress {
  action: BulkAction
  total: number
  done: number
  failed: number
  running: boolean
}

/** Rows per page; 0 = show all. */
export type PipelinePageSize = 25 | 50 | 100 | 0

interface ArmingPatch {
  enabled: boolean
  reviewerType: AutoVerdictReviewer
  mode: AutoVerdictMode
}

interface PipelineState {
  rows: PipelineRow[]
  version: number | null
  generatedAt: string | null
  prDataSyncedAt: string | null
  // True only while `rows` is empty and a load is in flight — the overlay
  // otherwise renders its last snapshot instantly and refreshes behind it.
  loading: boolean
  refreshing: boolean
  error: string | null
  includeClosed: boolean

  // Filters
  query: string
  stages: Set<PipelineStage>
  badgeFilters: Set<BadgeFilterKey>
  badgeFilterMode: BadgeFilterMode
  repo: string
  reviewerKey: string
  minRounds: number

  sort: PipelineSort
  selection: Set<string>
  expandedKey: string | null
  page: number
  pageSize: PipelinePageSize
  bulk: BulkProgress | null

  // Same poll-clobber guards as useSwimlaneStore: a fetch stamps `epoch` when
  // it starts and discards its response if a local mutation advanced it (or
  // polling is paused) by the time it lands.
  epoch: number
  pauseDepth: number

  load: () => Promise<void>
  refresh: () => Promise<void>
  setIncludeClosed: (v: boolean) => void
  pausePolling: () => void
  resumePolling: () => void

  patchRow: (row: PipelineRow) => void
  setArmingLocal: (repo: string, prNumber: number, arming: ArmingPatch) => void
  setCriteriaLocal: (repo: string, prNumber: number, override: AutoVerdictCriteriaOverride | null) => void
  setAutomationLocal: (repo: string, prNumber: number, automation: AutomationDispatchState) => void
  setOnBoardLocal: (key: string, onBoard: boolean) => void

  toggleSelect: (key: string) => void
  selectAll: (keys: string[]) => void
  clearSelection: () => void
  runBulk: (action: BulkAction, keys: string[]) => Promise<void>
  clearBulk: () => void

  setQuery: (q: string) => void
  toggleStage: (stage: PipelineStage) => void
  toggleBadgeFilter: (key: BadgeFilterKey) => void
  setBadgeFilterMode: (mode: BadgeFilterMode) => void
  clearBadgeFilters: () => void
  setRepo: (repo: string) => void
  setReviewerKey: (key: string) => void
  setMinRounds: (n: number) => void
  resetFilters: () => void

  setSort: (column: PipelineSortColumn) => void
  toggleExpanded: (key: string) => void
  setPage: (page: number) => void
  setPageSize: (size: PipelinePageSize) => void
}

const DEFAULT_SORT: PipelineSort = { column: 'stage', dir: 'asc' }
// Newest-first reads better for these; everything else defaults ascending.
const DESC_FIRST: PipelineSortColumn[] = ['updated', 'rounds', 'issues']

/** Keep the selection inside the current row set (rows can leave the
 * snapshot when they close or the include-closed toggle flips). */
function pruneSelection(selection: Set<string>, rows: PipelineRow[]): Set<string> {
  if (selection.size === 0) return selection
  const keys = new Set(rows.map((r) => r.key))
  const next = new Set<string>()
  for (const k of selection) if (keys.has(k)) next.add(k)
  return next.size === selection.size ? selection : next
}

export const usePipelineStore = create<PipelineState>((set, get) => {
  const updateRow = (
    match: (row: PipelineRow) => boolean,
    update: (row: PipelineRow) => PipelineRow,
  ) => {
    let found = false
    const rows = get().rows.map((r) => {
      if (!match(r)) return r
      found = true
      return update(r)
    })
    if (!found) return
    set((s) => ({ rows, epoch: s.epoch + 1 }))
  }

  const byPr = (repo: string, prNumber: number) => (r: PipelineRow) =>
    r.repo === repo && r.prNumber === prNumber

  // Shared fetch path. `silent` = background poll: no spinner, swallow errors.
  const fetchSnapshot = async (silent: boolean) => {
    if (silent && get().pauseDepth > 0) return
    const startEpoch = get().epoch
    const { version, includeClosed, rows } = get()
    if (silent) set({ refreshing: true })
    else set({ loading: rows.length === 0, error: null })
    try {
      const data = await fetchPipeline({ version, includeClosed })
      if (get().epoch !== startEpoch || get().pauseDepth > 0) {
        set({ loading: false, refreshing: false })
        return
      }
      if (data.unchanged) {
        set({ loading: false, refreshing: false })
        return
      }
      set((s) => ({
        rows: data.rows,
        version: data.version,
        generatedAt: data.generatedAt,
        prDataSyncedAt: data.prDataSyncedAt,
        selection: pruneSelection(s.selection, data.rows),
        loading: false,
        refreshing: false,
      }))
    } catch (e) {
      set({
        loading: false,
        refreshing: false,
        ...(silent ? {} : { error: e instanceof Error ? e.message : 'Failed to load the pipeline' }),
      })
    }
  }

  // One bulk-action step for one row. Throws on failure; the caller counts.
  const runRowAction = async (action: BulkAction, row: PipelineRow) => {
    switch (action) {
      case 'optout':
      case 'enroll': {
        const resp = action === 'optout'
          ? await optOutAutomationDispatch(row.repo, row.prNumber)
          : await enrollAutomationDispatch(row.repo, row.prNumber)
        if (resp.row) get().patchRow(resp.row)
        return
      }
      case 'arm':
      case 'disarm': {
        const arming: ArmingPatch = {
          enabled: action === 'arm',
          reviewerType: row.autoVerdict?.reviewerType ?? row.dispatch.reviewerKey ?? 'default',
          mode: row.autoVerdict?.mode ?? 'verdict',
        }
        await setCardAutoVerdict(row.prNumber, row.repo, arming)
        get().setArmingLocal(row.repo, row.prNumber, arming)
        return
      }
      case 'watch': {
        if (row.onBoard) return
        await addToQueue({
          number: row.prNumber,
          title: row.title ?? `#${row.prNumber}`,
          url: prUrl(row),
          author: row.author ?? '',
          repo: row.repo,
          additions: row.additions ?? undefined,
          deletions: row.deletions ?? undefined,
        })
        get().setOnBoardLocal(row.key, true)
        return
      }
    }
  }

  return {
    rows: [],
    version: null,
    generatedAt: null,
    prDataSyncedAt: null,
    loading: false,
    refreshing: false,
    error: null,
    includeClosed: false,

    query: '',
    stages: new Set<PipelineStage>(),
    badgeFilters: new Set<BadgeFilterKey>(),
    badgeFilterMode: 'OR',
    repo: '',
    reviewerKey: '',
    minRounds: 0,

    sort: DEFAULT_SORT,
    selection: new Set<string>(),
    expandedKey: null,
    page: 1,
    pageSize: 25,
    bulk: null,

    epoch: 0,
    pauseDepth: 0,

    load: () => fetchSnapshot(false),
    refresh: () => fetchSnapshot(true),

    setIncludeClosed: (v) => {
      // The version short-circuit doesn't know about the toggle, so drop it to
      // force a full payload.
      set({ includeClosed: v, version: null, page: 1 })
      void fetchSnapshot(false)
    },

    pausePolling: () => set((s) => ({ pauseDepth: s.pauseDepth + 1 })),
    resumePolling: () => set((s) => ({ pauseDepth: Math.max(0, s.pauseDepth - 1) })),

    patchRow: (row) => {
      const rows = get().rows
      const idx = rows.findIndex((r) => r.key === row.key)
      const next = idx === -1 ? [...rows, row] : rows.map((r, i) => (i === idx ? row : r))
      set((s) => ({ rows: next, epoch: s.epoch + 1 }))
    },

    setArmingLocal: (repo, prNumber, arming) =>
      updateRow(byPr(repo, prNumber), (r) => ({
        ...r,
        autoVerdict: {
          ...arming,
          // Arming says nothing about the override or the last outcome.
          criteriaOverride: r.autoVerdict?.criteriaOverride ?? null,
          last: r.autoVerdict?.last ?? null,
        },
      })),

    setCriteriaLocal: (repo, prNumber, override) =>
      updateRow(byPr(repo, prNumber), (r) => ({
        ...r,
        autoVerdict: {
          enabled: r.autoVerdict?.enabled ?? false,
          reviewerType: r.autoVerdict?.reviewerType ?? 'default',
          mode: r.autoVerdict?.mode ?? 'verdict',
          last: r.autoVerdict?.last ?? null,
          criteriaOverride: override,
        },
      })),

    setAutomationLocal: (repo, prNumber, automation) =>
      updateRow(byPr(repo, prNumber), (r) => ({ ...r, automation })),

    setOnBoardLocal: (key, onBoard) =>
      updateRow((r) => r.key === key, (r) => ({
        ...r,
        onBoard,
        queueItemId: onBoard ? r.queueItemId : null,
        notesCount: onBoard ? r.notesCount : 0,
      })),

    toggleSelect: (key) =>
      set((s) => {
        const next = new Set(s.selection)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return { selection: next }
      }),
    selectAll: (keys) => set({ selection: new Set(keys) }),
    clearSelection: () => set({ selection: new Set<string>() }),

    runBulk: async (action, keys) => {
      const rowsByKey = new Map(get().rows.map((r) => [r.key, r]))
      const targets = keys.flatMap((k) => {
        const row = rowsByKey.get(k)
        return row ? [row] : []
      })
      set({ bulk: { action, total: targets.length, done: 0, failed: 0, running: true } })
      get().pausePolling()
      try {
        await Promise.all(
          targets.map(async (row) => {
            try {
              await runRowAction(action, row)
              set((s) => ({ bulk: s.bulk && { ...s.bulk, done: s.bulk.done + 1 } }))
            } catch {
              set((s) => ({ bulk: s.bulk && { ...s.bulk, failed: s.bulk.failed + 1 } }))
            }
          }),
        )
      } finally {
        // Bump the epoch so a poll that started before the bulk run can't
        // land its pre-mutation snapshot after we resume.
        set((s) => ({ bulk: s.bulk && { ...s.bulk, running: false }, epoch: s.epoch + 1 }))
        get().resumePolling()
      }
      if (action === 'watch') {
        // Keep the header's queue count honest.
        fetchMergeQueue()
          .then((resp) => useQueueStore.getState().setMergeQueue(resp.queue))
          .catch(() => null)
      }
    },
    clearBulk: () => set({ bulk: null }),

    setQuery: (q) => set({ query: q, page: 1 }),
    toggleStage: (stage) =>
      set((s) => {
        const next = new Set(s.stages)
        if (next.has(stage)) next.delete(stage)
        else next.add(stage)
        return { stages: next, page: 1 }
      }),
    toggleBadgeFilter: (key) =>
      set((s) => {
        const next = new Set(s.badgeFilters)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return { badgeFilters: next, page: 1 }
      }),
    setBadgeFilterMode: (mode) => set({ badgeFilterMode: mode, page: 1 }),
    clearBadgeFilters: () => set({ badgeFilters: new Set<BadgeFilterKey>(), page: 1 }),
    setRepo: (repo) => set({ repo, page: 1 }),
    setReviewerKey: (key) => set({ reviewerKey: key, page: 1 }),
    setMinRounds: (n) => set({ minRounds: Math.max(0, Math.floor(n) || 0), page: 1 }),
    resetFilters: () =>
      set({
        query: '',
        stages: new Set<PipelineStage>(),
        badgeFilters: new Set<BadgeFilterKey>(),
        repo: '',
        reviewerKey: '',
        minRounds: 0,
        page: 1,
      }),

    setSort: (column) =>
      set((s) => {
        if (s.sort.column === column) {
          return { sort: { column, dir: s.sort.dir === 'asc' ? 'desc' : 'asc' }, page: 1 }
        }
        return { sort: { column, dir: DESC_FIRST.includes(column) ? 'desc' : 'asc' }, page: 1 }
      }),
    toggleExpanded: (key) => set((s) => ({ expandedKey: s.expandedKey === key ? null : key })),
    setPage: (page) => set({ page }),
    setPageSize: (size) => set({ pageSize: size, page: 1 }),
  }
})
