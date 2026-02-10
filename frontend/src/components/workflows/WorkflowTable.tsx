import { useWorkflowStore } from '../../stores/useWorkflowStore'
import { SortableTable, Column } from '../common/SortableTable'
import { Pagination } from '../common/Pagination'
import { Badge } from '../common/Badge'
import { formatDuration, formatRelativeTime } from '../../utils/formatters'
import type { WorkflowRun } from '../../api/types'

interface WorkflowTableProps {
  runs: WorkflowRun[]
}

const PAGE_SIZE_OPTIONS = [25, 50, 100]

export function WorkflowTable({ runs }: WorkflowTableProps) {
  const {
    sortBy,
    sortDirection,
    currentPage,
    workflowsPerPage,
    sortWorkflows,
    setCurrentPage,
    setWorkflowsPerPage,
    getPaginatedWorkflows,
    getTotalPages,
  } = useWorkflowStore()

  const paginatedRuns = getPaginatedWorkflows()
  const totalPages = getTotalPages()

  const getConclusionBadge = (conclusion: string | null, status: string) => {
    if (status === 'in_progress' || status === 'queued') {
      return <Badge variant="warning">In Progress</Badge>
    }

    switch (conclusion) {
      case 'success':
        return <Badge variant="success">Success</Badge>
      case 'failure':
        return <Badge variant="error">Failure</Badge>
      case 'cancelled':
        return <Badge variant="neutral">Cancelled</Badge>
      case 'skipped':
        return <Badge variant="neutral">Skipped</Badge>
      default:
        return <Badge variant="neutral">{conclusion || status}</Badge>
    }
  }

  const columns: Column<WorkflowRun>[] = [
    {
      key: 'name',
      label: 'Workflow',
      sortable: true,
      tooltip: 'GitHub Actions workflow name and run title',
      render: (run) => (
        <div className="mx-workflow-cell">
          <a
            href={run.html_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mx-workflow-link"
          >
            {run.name}
          </a>
          <span className="mx-workflow-title">{run.display_title}</span>
        </div>
      ),
    },
    {
      key: 'conclusion',
      label: 'Status',
      sortable: true,
      tooltip: 'Final outcome of the workflow run',
      render: (run) => getConclusionBadge(run.conclusion, run.status),
    },
    {
      key: 'head_branch',
      label: 'Branch',
      sortable: true,
      tooltip: 'Branch that triggered the workflow run',
    },
    {
      key: 'event',
      label: 'Event',
      sortable: true,
      tooltip: 'Trigger event type (push, pull_request, schedule, etc.)',
      render: (run) => <span className="mx-workflow-event">{run.event}</span>,
    },
    {
      key: 'actor_login',
      label: 'Actor',
      sortable: true,
      tooltip: 'User who triggered the workflow run',
    },
    {
      key: 'duration_seconds',
      label: 'Duration',
      sortable: true,
      tooltip: 'Time from start to completion',
      render: (run) => formatDuration(run.duration_seconds),
    },
    {
      key: 'created_at',
      label: 'Started',
      sortable: true,
      tooltip: 'When the workflow run was created',
      render: (run) => (
        <span data-tooltip={new Date(run.created_at).toLocaleString()}>
          {formatRelativeTime(run.created_at)}
        </span>
      ),
    },
  ]

  return (
    <div className="mx-workflow-table">
      <SortableTable
        columns={columns}
        data={paginatedRuns}
        sortBy={sortBy}
        sortDirection={sortDirection}
        onSort={sortWorkflows}
        keyExtractor={(run) => run.id}
      />

      <div className="mx-workflow-table__footer">
        <div className="mx-workflow-table__page-size">
          <label>Rows per page:</label>
          <select
            value={workflowsPerPage}
            onChange={(e) => setWorkflowsPerPage(Number(e.target.value))}
            className="mx-select__field"
          >
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
        </div>

        {totalPages > 1 && (
          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            totalItems={runs.length}
            onPageChange={setCurrentPage}
          />
        )}
      </div>
    </div>
  )
}
