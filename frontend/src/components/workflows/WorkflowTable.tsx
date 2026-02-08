import { useWorkflowStore } from '../../stores/useWorkflowStore'
import { SortableTable, Column } from '../common/SortableTable'
import { Pagination } from '../common/Pagination'
import { Badge } from '../common/Badge'
import { formatDuration, formatRelativeTime } from '../../utils/formatters'
import type { WorkflowRun } from '../../api/types'

interface WorkflowTableProps {
  runs: WorkflowRun[]
}

export function WorkflowTable({ runs }: WorkflowTableProps) {
  const {
    workflowSortBy,
    workflowSortDirection,
    workflowPage,
    sortWorkflows,
    setWorkflowPage,
    getSortedWorkflowRuns,
    getTotalWorkflowPages,
  } = useWorkflowStore()

  const sortedRuns = getSortedWorkflowRuns()
  const totalPages = getTotalWorkflowPages()

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
        return <Badge variant="default">Cancelled</Badge>
      case 'skipped':
        return <Badge variant="default">Skipped</Badge>
      default:
        return <Badge variant="default">{conclusion || status}</Badge>
    }
  }

  const columns: Column<WorkflowRun>[] = [
    {
      key: 'name',
      label: 'Workflow',
      sortable: true,
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
      render: (run) => getConclusionBadge(run.conclusion, run.status),
    },
    {
      key: 'head_branch',
      label: 'Branch',
      sortable: true,
    },
    {
      key: 'event',
      label: 'Event',
      sortable: true,
      render: (run) => <span className="mx-workflow-event">{run.event}</span>,
    },
    {
      key: 'actor_login',
      label: 'Actor',
      sortable: true,
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
        <span title={new Date(run.created_at).toLocaleString()}>
          {formatRelativeTime(run.created_at)}
        </span>
      ),
    },
  ]

  return (
    <div className="mx-workflow-table">
      <SortableTable
        columns={columns}
        data={sortedRuns}
        sortBy={workflowSortBy}
        sortDirection={workflowSortDirection}
        onSort={sortWorkflows}
        keyExtractor={(run) => run.id}
      />

      {totalPages > 1 && (
        <Pagination
          currentPage={workflowPage}
          totalPages={totalPages}
          totalItems={runs.length}
          onPageChange={setWorkflowPage}
        />
      )}
    </div>
  )
}
