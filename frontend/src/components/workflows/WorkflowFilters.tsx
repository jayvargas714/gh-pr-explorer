import { useWorkflowStore } from '../../stores/useWorkflowStore'
import { Select } from '../common/Select'
import { Button } from '../common/Button'

interface WorkflowFiltersProps {
  workflows: Array<{ id: number; name: string }>
  onRefreshCache: () => void
  refreshing: boolean
}

export function WorkflowFilters({ workflows, onRefreshCache, refreshing }: WorkflowFiltersProps) {
  const {
    workflowFilter,
    eventFilter,
    conclusionFilter,
    setWorkflowFilter,
    setEventFilter,
    setConclusionFilter,
    resetFilters,
  } = useWorkflowStore()

  const eventOptions = [
    { value: '', label: 'All Events' },
    { value: 'push', label: 'Push' },
    { value: 'pull_request', label: 'Pull Request' },
    { value: 'schedule', label: 'Schedule' },
    { value: 'workflow_dispatch', label: 'Manual' },
    { value: 'release', label: 'Release' },
  ]

  const conclusionOptions = [
    { value: '', label: 'All Results' },
    { value: 'success', label: 'Success' },
    { value: 'failure', label: 'Failure' },
    { value: 'cancelled', label: 'Cancelled' },
    { value: 'skipped', label: 'Skipped' },
  ]

  const workflowOptions = [
    { value: '', label: 'All Workflows' },
    ...workflows.map((w) => ({ value: String(w.id), label: w.name })),
  ]

  return (
    <div className="mx-workflow-filters">
      <div className="mx-workflow-filters__row">
        <Select
          label="Workflow"
          value={workflowFilter}
          onChange={(e) => setWorkflowFilter(e.target.value)}
          options={workflowOptions}
        />

        <Select
          label="Event"
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
          options={eventOptions}
        />

        <Select
          label="Result"
          value={conclusionFilter}
          onChange={(e) => setConclusionFilter(e.target.value)}
          options={conclusionOptions}
        />

        <Button variant="secondary" size="sm" onClick={resetFilters}>
          Reset Filters
        </Button>

        <Button
          variant="secondary"
          size="sm"
          onClick={onRefreshCache}
          disabled={refreshing}
          title="Fetch latest workflow runs from GitHub"
        >
          {refreshing ? 'Refreshing...' : 'Refresh Cache'}
        </Button>
      </div>
    </div>
  )
}
