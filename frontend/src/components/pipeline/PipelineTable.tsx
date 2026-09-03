import { Fragment } from 'react'
import { PipelinePageSize, usePipelineStore } from '../../stores/usePipelineStore'
import { Pagination } from '../common/Pagination'
import { PipelineRow } from './PipelineRow'
import { PipelineRowDetail } from './PipelineRowDetail'
import { PipelineSortColumn } from './pipelineFilters'
import { useFilteredRows } from './useFilteredRows'

const PAGE_SIZES: PipelinePageSize[] = [25, 50, 100, 0]

const COLUMNS: { key: PipelineSortColumn; label: string; tooltip?: string }[] = [
  { key: 'pr', label: 'PR' },
  { key: 'stage', label: 'Stage' },
  { key: 'rounds', label: 'Rounds', tooltip: 'Review rounds recorded (hover the badge for the rev log)' },
  { key: 'auto', label: 'Auto', tooltip: 'Auto-verdict arming' },
  { key: 'ci', label: 'CI' },
  { key: 'review', label: 'Review' },
  { key: 'issues', label: 'Issues', tooltip: 'Critical / Major / Minor — posted/found' },
  { key: 'updated', label: 'Updated' },
]

export function PipelineTable() {
  const filtered = useFilteredRows()
  const totalRows = usePipelineStore((s) => s.rows.length)
  const sort = usePipelineStore((s) => s.sort)
  const setSort = usePipelineStore((s) => s.setSort)
  const selection = usePipelineStore((s) => s.selection)
  const selectAll = usePipelineStore((s) => s.selectAll)
  const clearSelection = usePipelineStore((s) => s.clearSelection)
  const expandedKey = usePipelineStore((s) => s.expandedKey)
  const page = usePipelineStore((s) => s.page)
  const pageSize = usePipelineStore((s) => s.pageSize)
  const setPage = usePipelineStore((s) => s.setPage)
  const setPageSize = usePipelineStore((s) => s.setPageSize)

  // Clamp rather than store: a poll that shrinks the list can strand the
  // saved page past the end.
  const totalPages = pageSize === 0 ? 1 : Math.max(1, Math.ceil(filtered.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const pageRows =
    pageSize === 0 ? filtered : filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  const filteredKeys = filtered.map((r) => r.key)
  const selectedVisible = filteredKeys.filter((k) => selection.has(k)).length
  const allSelected = filtered.length > 0 && selectedVisible === filtered.length

  if (totalRows === 0) {
    return <div className="mx-pipe-empty">The pipeline is empty — enroll a PR with 🤖+ from its card.</div>
  }

  return (
    <div className="mx-pipe-table-wrap">
      <div className="mx-table-wrapper mx-pipe-table-scroll">
        <table className="mx-table mx-pipe-table">
          <thead>
            <tr>
              <th className="mx-pipe-table__check">
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = selectedVisible > 0 && !allSelected
                  }}
                  onChange={() => (allSelected ? clearSelection() : selectAll(filteredKeys))}
                  aria-label="Select all visible rows"
                />
              </th>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={`mx-table__header--sortable mx-pipe-table__col-${col.key}`}
                  onClick={() => setSort(col.key)}
                  data-tooltip={col.tooltip}
                  aria-sort={
                    sort.column === col.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'
                  }
                >
                  {col.label}
                  {sort.column === col.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅'}
                </th>
              ))}
              <th className="mx-pipe-table__col-actions" />
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length + 2} className="mx-pipe-table__no-match">
                  No rows match the current filters.
                </td>
              </tr>
            ) : (
              pageRows.map((row) => (
                <Fragment key={row.key}>
                  <PipelineRow
                    row={row}
                    selected={selection.has(row.key)}
                    expanded={expandedKey === row.key}
                  />
                  {expandedKey === row.key && (
                    <tr className="mx-pipe-detail-row">
                      <td colSpan={COLUMNS.length + 2}>
                        <PipelineRowDetail row={row} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="mx-pipe-pager">
        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          totalItems={filtered.length}
          onPageChange={setPage}
        />
        <select
          className="mx-select mx-pipe-select"
          value={pageSize}
          onChange={(e) => setPageSize(Number(e.target.value) as PipelinePageSize)}
          aria-label="Rows per page"
        >
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>{n === 0 ? 'All' : `${n} / page`}</option>
          ))}
        </select>
      </div>
    </div>
  )
}
