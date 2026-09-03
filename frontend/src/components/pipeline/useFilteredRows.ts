import { useMemo } from 'react'
import type { PipelineRow } from '../../api/types'
import { usePipelineStore } from '../../stores/usePipelineStore'
import { compareRows, rowPassesFilters } from './pipelineFilters'

/** Rows after the store's filters and sort — shared by the table and the
 * header's match count. */
export function useFilteredRows(): PipelineRow[] {
  const rows = usePipelineStore((s) => s.rows)
  const query = usePipelineStore((s) => s.query)
  const stages = usePipelineStore((s) => s.stages)
  const badgeFilters = usePipelineStore((s) => s.badgeFilters)
  const badgeFilterMode = usePipelineStore((s) => s.badgeFilterMode)
  const repo = usePipelineStore((s) => s.repo)
  const reviewerKey = usePipelineStore((s) => s.reviewerKey)
  const minRounds = usePipelineStore((s) => s.minRounds)
  const sort = usePipelineStore((s) => s.sort)
  return useMemo(() => {
    const filters = { query, stages, badgeFilters, badgeFilterMode, repo, reviewerKey, minRounds }
    return rows.filter((r) => rowPassesFilters(r, filters)).sort(compareRows(sort))
  }, [rows, query, stages, badgeFilters, badgeFilterMode, repo, reviewerKey, minRounds, sort])
}
